import logging
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import Groq
from dotenv import load_dotenv
import os
import json
from typing import Optional

from routes.upload import router as upload_router
from routes.insights import router as insights_router
from routes.auth import router as auth_router
from routes.admin import router as admin_router
from routes.chat import router as chat_router
from routes.alerts import router as alerts_router
from database.db import engine
from database.models import Base, ChatMessage

from services.query_router import classify
from services.direct_query_handler import handle as direct_handle
from services.context_cache import get_focused_context
from services.auth import get_active_user
from services.tools import execute_tool, schemas as tool_schemas
from database.migration import run_migrations_and_seed
from services.scheduler import start_scheduler, stop_scheduler
from services.embeddings import preload_model_async
from services.embeddings import search_chat_memories, save_chat_memory
from services.agent_graph import run_agent_graph
from services.rate_limiter import check_rate_limit

from sqlalchemy import text
from database.db import SessionLocal

load_dotenv()

# Setup logging configuration for production
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("bizassist")

app = FastAPI(title="BizAssist API")

# Run DB migration and seeds
run_migrations_and_seed()

# Start proactive alert scheduler
start_scheduler()

# Pre-load embedding model in background so first request is instant
preload_model_async()


@app.on_event("shutdown")
def shutdown_event():
    stop_scheduler()

import os as _os
_default_origins = (
    "null,"
    "http://localhost:5500,http://127.0.0.1:5500,"
    "http://localhost:3000,"
    "http://localhost:5173,http://127.0.0.1:5173,"
    # Vercel production — update with your real Vercel URL
    "https://bizassist-react.vercel.app,"
    "https://bizassist.vercel.app,"
    # Hugging Face Spaces — format: https://<owner>-<space-name>.hf.space
    # Set ALLOWED_ORIGINS env var in HF Space secrets to add your exact URL
    "https://rakshit-dev-bizassist.hf.space"
)
_allowed_origins = [
    o.strip() for o in _os.getenv("ALLOWED_ORIGINS", _default_origins).split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    # Auth is via the Authorization Bearer header (not cookies), so credentialed
    # CORS isn't needed — and disabling it lets the "null" file:// origin work.
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(upload_router)
app.include_router(insights_router)
app.include_router(chat_router)
app.include_router(alerts_router)

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ── Model tiers ───────────────────────────────────────────────────────
# AI_SIMPLE  → fast cheap model, handles narrow factual queries
# AI_COMPLEX → larger model, reserved for analysis / planning / strategy
MODEL_SIMPLE  = os.getenv("GROQ_MODEL_SIMPLE",  "llama-3.1-8b-instant")
MODEL_COMPLEX = os.getenv("GROQ_MODEL_COMPLEX", "llama-3.3-70b-versatile")


class Prompt(BaseModel):
    message: str
    user_id: Optional[int] = None
    session_id: Optional[str] = None


@app.get("/")
def home():
    return {"message": "BizAssist AI server running"}


@app.post("/ask")
def ask_ai(prompt: Prompt, current_user: dict = Depends(get_active_user)):
    """
    Hybrid AI endpoint.

    DIRECT path  →  DB query only, 0 tokens, ~5ms
    AI path      →  cached context + Groq, ~300-600 tokens
    """

    try:

        user_query = prompt.message.strip()

        # Determine user_id
        active_user_id = current_user["id"]

        # Determine session_id and title
        session_id = prompt.session_id
        if not session_id:
            import uuid
            session_id = str(uuid.uuid4())

        # Check if session exists and resolve/set session title
        db = SessionLocal()
        session_title = "Untitled Conversation"
        try:
            existing_count = db.query(ChatMessage).filter(
                ChatMessage.business_id == active_user_id,
                ChatMessage.session_id == session_id
            ).count()
            
            if existing_count == 0:
                session_title = user_query[:40] + ("..." if len(user_query) > 40 else "")
            else:
                first_msg = db.query(ChatMessage).filter(
                    ChatMessage.business_id == active_user_id,
                    ChatMessage.session_id == session_id
                ).order_by(ChatMessage.id.asc()).first()
                if first_msg and first_msg.session_title:
                    session_title = first_msg.session_title
        except Exception as e:
            logger.error(f"Error checking session title: {str(e)}", exc_info=True)
        finally:
            db.close()

        # Fetch last 10 chronological chat messages for active user & active session
        db = SessionLocal()
        history = []
        try:
            history_rows = (
                db.query(ChatMessage)
                .filter(
                    ChatMessage.business_id == active_user_id,
                    ChatMessage.session_id == session_id
                )
                .order_by(ChatMessage.id.desc())
                .limit(10)
                .all()
            )
            for m in reversed(history_rows):
                history.append({"role": m.role, "content": m.content})
        except Exception as e:
            logger.error(f"Error fetching chat history: {str(e)}", exc_info=True)
        finally:
            db.close()

        import hashlib
        history_str = json.dumps(history)

        # ── Layer 1: classify ────────────────────────────────────
        route, handler_key = classify(user_query, has_history=len(history) > 0)

        # ── Rate limit check ─────────────────────────────────────
        rl = check_rate_limit(active_user_id, route)
        if not rl["allowed"]:
            logger.warning(f"[RateLimit] Blocked user {active_user_id}: {rl['reason']}")
            return {
                "error":       rl["reason"],
                "limit":       rl.get("limit"),
                "used":        rl.get("used"),
                "retry_after": rl.get("retry_after"),
                "status_code": 429
            }

        # Cache salt strategy:
        # AI_COMPLEX → query + business only (data-driven answer, history irrelevant)
        #              Same query = same DB data = same answer regardless of chat context
        # AI_SIMPLE  → query + session history (conversational, context matters)
        if route == "AI_COMPLEX":
            history_salt = hashlib.md5(f"{active_user_id}:{user_query}".encode("utf-8")).hexdigest()
        else:
            history_salt = hashlib.md5(f"{session_id}:{history_str}".encode("utf-8")).hexdigest()

        # ── Layer 2: direct DB answer ────────────────────────────
        if route == "DIRECT":
            answer = direct_handle(handler_key, user_query, active_user_id)

            if answer:
                logger.info(f"[BizAssist Router Decision] -> DIRECT/DB Path | Handler: {handler_key} | Query: '{user_query}'")
                
                # Log transaction to DB
                db = SessionLocal()
                try:
                    db.add(ChatMessage(
                        business_id=active_user_id,
                        role="user",
                        content=user_query,
                        session_id=session_id,
                        session_title=session_title
                    ))
                    db.add(ChatMessage(
                        business_id=active_user_id,
                        role="assistant",
                        content=answer,
                        session_id=session_id,
                        session_title=session_title
                    ))
                    db.commit()
                except Exception as e:
                    db.rollback()
                    logger.error(f"Error logging DIRECT query/response: {str(e)}", exc_info=True)
                finally:
                    db.close()

                return {
                    "response" : answer,
                    "source"   : "db",      # tells frontend: no AI token used
                    "session_id": session_id,
                    "session_title": session_title
                }
            # If handler returned None (DB error), fall through to AI

        # ── Layer 2.5: check query response cache ────────────────
        from services.context_cache import get_cached_query_response, set_cached_query_response
        cached_response = get_cached_query_response(active_user_id, user_query, history_salt)
        if cached_response:
            logger.info(f"[BizAssist Cache Hit] -> Returning cached AI response for query: '{user_query}'")
            
            # Log transaction to DB
            db = SessionLocal()
            try:
                db.add(ChatMessage(
                    business_id=active_user_id,
                    role="user",
                    content=user_query,
                    session_id=session_id,
                    session_title=session_title
                ))
                db.add(ChatMessage(
                    business_id=active_user_id,
                    role="assistant",
                    content=cached_response["response"],
                    session_id=session_id,
                    session_title=session_title
                ))
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(f"Error logging cached transaction: {str(e)}", exc_info=True)
            finally:
                db.close()

            cached_copy = cached_response.copy()
            cached_copy["cached"] = True
            cached_copy["session_id"] = session_id
            cached_copy["session_title"] = session_title
            return cached_copy

        # ── Layer 3a: AI_COMPLEX → LangGraph multi-agent pipeline ───
        if route == "AI_COMPLEX":
            logger.info(f"[BizAssist Router Decision] -> AI_COMPLEX | LangGraph agents | Query: '{user_query}'")
            final_response = run_agent_graph(
                user_query=user_query,
                business_id=active_user_id,
                history=history
            )
            selected_model = MODEL_COMPLEX

        # ── Layer 3b: AI_SIMPLE → single agent + tool calling ────────
        else:
            selected_model = MODEL_SIMPLE
            logger.info(f"[BizAssist Router Decision] -> AI_SIMPLE | Model: {selected_model} | Query: '{user_query}'")

            SYSTEM_PROMPT = (
                "You are BIZASSIST, an AI business advisor for Indian retail stores (pharmacies, supermarkets).\n"
                "Rules:\n"
                "- Facts only. Never invent numbers. Use ₹. Name customers/amounts/dates.\n"
                "- Use tools to fetch live data before answering.\n"
                "- Overdue invoices → suggest follow-up. Low stock → suggest reorder. Expiring items → suggest discounts.\n"
                "- Scope: retail operations, invoices, inventory, payments, cash flow only. Refuse off-topic questions.\n"
                "- Tool args must be valid JSON (no trailing commas).\n"
            )

            messages = [{"role": "system", "content": SYSTEM_PROMPT}]

            past_memories = search_chat_memories(active_user_id, user_query, limit=3)
            if past_memories:
                messages.append({"role": "system", "content": f"[Relevant past context]\n{past_memories}"})

            for msg in history:
                messages.append({"role": msg["role"], "content": msg["content"]})
            messages.append({"role": "user", "content": user_query})

            completion = client.chat.completions.create(
                messages=messages,
                model=selected_model,
                temperature=0.1,
                max_tokens=800,
                tools=tool_schemas,
                tool_choice="auto"
            )

            response_message = completion.choices[0].message
            tool_calls       = response_message.tool_calls

            if tool_calls:
                messages.append(response_message)
                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments or "{}")
                    tool_response = execute_tool(function_name, function_args, active_user_id)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": function_name,
                        "content": tool_response
                    })
                second_completion = client.chat.completions.create(
                    messages=messages,
                    model=selected_model,
                    temperature=0.1,
                    max_tokens=800
                )
                final_response = second_completion.choices[0].message.content
            else:
                final_response = response_message.content

            # Token usage logging for AI_SIMPLE
            try:
                from database.models import TokenUsage
                usage    = completion.usage
                total_in = (usage.prompt_tokens or 0)
                total_out = (usage.completion_tokens or 0)
                if tool_calls:
                    sec = second_completion.usage
                    total_in  += (sec.prompt_tokens or 0)
                    total_out += (sec.completion_tokens or 0)
                db = SessionLocal()
                try:
                    db.add(TokenUsage(
                        business_id   = active_user_id,
                        model         = selected_model,
                        model_tier    = route,
                        input_tokens  = total_in,
                        output_tokens = total_out,
                        total_tokens  = total_in + total_out,
                    ))
                    db.commit()
                finally:
                    db.close()
            except Exception as te:
                logger.warning(f"[Tokens] Failed to log usage: {te}")

        ai_response = {
            "response"    : final_response,
            "source"      : "ai",
            "model_tier"  : route,
            "model_used"  : selected_model,
            "session_id"  : session_id,
            "session_title": session_title
        }

        # Log transaction to DB
        db = SessionLocal()
        try:
            db.add(ChatMessage(
                business_id=active_user_id,
                role="user",
                content=user_query,
                session_id=session_id,
                session_title=session_title
            ))
            db.add(ChatMessage(
                business_id=active_user_id,
                role="assistant",
                content=final_response,
                session_id=session_id,
                session_title=session_title
            ))
            db.commit()

            # Save QA turn to Chroma persistent vector database
            save_chat_memory(
                business_id=active_user_id,
                session_id=session_id,
                session_title=session_title,
                user_query=user_query,
                assistant_response=final_response
            )
        except Exception as e:
            db.rollback()
            logger.error(f"Error logging AI transaction: {str(e)}", exc_info=True)
        finally:
            db.close()

        set_cached_query_response(active_user_id, user_query, ai_response, history_salt)
        return ai_response

    except Exception as e:
        error_str = str(e)
        logger.error(f"Error handling AI ask request: {error_str}", exc_info=True)
        
        # Check for rate limit / quota exceeded (429)
        if "429" in error_str or "rate_limit" in error_str.lower() or "quota" in error_str.lower():
            return {
                "error": "API quota exceeded. Rate limit hit. Please wait a moment and try again.",
                "status_code": 429
            }
        
        return {
            "error": "An internal error occurred while processing your request.",
            "status_code": 500
        }