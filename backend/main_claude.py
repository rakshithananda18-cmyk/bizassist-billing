import logging
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic
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
from services.embeddings import search_chat_memories, save_chat_memory

from sqlalchemy import text
from database.db import SessionLocal

load_dotenv()

# Setup logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("bizassist")

app = FastAPI(title="BizAssist API - Claude")

# Run DB migration and seeds
run_migrations_and_seed()

# Start proactive alert scheduler
start_scheduler()


@app.on_event("shutdown")
def shutdown_event():
    stop_scheduler()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(upload_router)
app.include_router(insights_router)
app.include_router(chat_router)
app.include_router(alerts_router)

client = anthropic.Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))


class Prompt(BaseModel):
    message: str
    user_id: Optional[int] = None
    session_id: Optional[str] = None


def convert_to_claude_tools(openai_schemas):
    """Converts OpenAI format tool schemas to Anthropic format schemas."""
    claude_tools = []
    for s in openai_schemas:
        if s.get("type") == "function":
            func = s["function"]
            claude_tool = {
                "name": func["name"],
                "description": func["description"]
            }
            if "parameters" in func:
                claude_tool["input_schema"] = func["parameters"]
            else:
                claude_tool["input_schema"] = {
                    "type": "object",
                    "properties": {}
                }
            claude_tools.append(claude_tool)
    return claude_tools


@app.get("/")
def home():
    return {"message": "BizAssist AI Claude server running"}


@app.post("/ask")
def ask_ai(prompt: Prompt, current_user: dict = Depends(get_active_user)):
    """
    Hybrid AI endpoint using Claude.
    
    DIRECT path  →  DB query only, 0 tokens, ~5ms
    AI path      →  cached context + Claude, ~300-600 tokens
    """
    try:
        user_query = prompt.message.strip()
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

        # Generate a cache salt based on the session ID and current session's recent chat history
        import hashlib
        history_str = json.dumps(history)
        history_salt = hashlib.md5(f"{session_id}:{history_str}".encode("utf-8")).hexdigest()

        # ── Layer 1: classify ────────────────────────────────────
        route, handler_key = classify(user_query)

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
                    "source"   : "db",
                    "session_id": session_id,
                    "session_title": session_title
                }

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

        # ── Layer 3: Claude with Tool Calling ──────────────────────
        logger.info(f"[BizAssist Router Decision] -> AI/Tool Calling Path (Claude) | Query: '{user_query}'")
        
        # Retrieve past memories across sessions
        past_memories = search_chat_memories(active_user_id, user_query, limit=3)
        
        system_prompt = (
            "You are BIZASSIST, a proactive AI business intelligence and growth advisor "
            "for Indian retail businesses (pharmacies, supermarkets, stores).\n\n"
            "Core Advisor Rules:\n"
            "- Never invent numbers. Always be factual and base recommendations on real database metrics.\n"
            "- Use ₹ for Indian Rupees. Be specific: name customers, amounts, and dates where available.\n"
            "- Format lists with bullet points. Keep answers structured and highly readable.\n"
            "- Actively identify opportunities for business growth, cash flow optimization, and cost savings:\n"
            "  * If there are overdue invoices or unpaid accounts: identify the top debtors and suggest polite, systematic follow-up strategies to recover cash quickly.\n"
            "  * If there are low-stock products: warn the user and recommend optimal reorder times to avoid stockouts and lost sales.\n"
            "  * If there are expiring products: suggest promotional pricing, bundles, or discounts to clear them out before they expire and minimize waste.\n"
            "  * If analyzing customer data: identify high-value customers and suggest retention strategies (e.g., personalized loyalty offers, volume discounts).\n"
            "- Translate raw financial metrics into clear, actionable advice that directly helps the user grow their business.\n"
            "- For client dues or unpaid accounts, default to checking invoices first.\n"
            "- STRICT SCOPE FILTER: You are a dedicated retail business operations and intelligence assistant. Politely refuse to answer any queries that are not related to retail store business operations, inventory, billing, sales, invoices, cash flows, or business growth. If asked about personal topics, health/diet, recipes, general knowledge, or other non-business subjects, politely state that your capabilities are strictly focused on business assistance.\n"
            "- Ensure function call arguments are strictly valid JSON with NO trailing commas (e.g. use {\"status\": \"Pending\"}, never {\"status\": \"Pending\",}).\n"
        )
        
        if past_memories:
            system_prompt += f"\n\n{past_memories}"

        claude_tools = convert_to_claude_tools(tool_schemas)

        # Construct alternating messages for Anthropic
        messages = []
        for msg in history:
            role = msg["role"]
            if role == "bot" or role == "assistant":
                messages.append({"role": "assistant", "content": msg["content"]})
            else:
                messages.append({"role": "user", "content": msg["content"]})
        
        # Add the current user query
        messages.append({"role": "user", "content": user_query})

        completion = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=800,
            temperature=0.1,
            system=system_prompt,
            messages=messages,
            tools=claude_tools
        )

        # Check for tool use blocks
        tool_calls = [block for block in completion.content if block.type == "tool_use"]
        
        if tool_calls:
            # Append the assistant's request with the tool call block
            messages.append({"role": "assistant", "content": completion.content})
            
            tool_result_content = []
            for tool_call in tool_calls:
                function_name = tool_call.name
                function_args = tool_call.input  # Anthropics returns parsed dictionary
                
                tool_response = execute_tool(function_name, function_args, active_user_id)
                
                tool_result_content.append({
                    "type": "tool_result",
                    "tool_use_id": tool_call.id,
                    "content": tool_response
                })
            
            # Send the tool responses back as a user message
            messages.append({
                "role": "user",
                "content": tool_result_content
            })
            
            second_completion = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=800,
                temperature=0.1,
                system=system_prompt,
                messages=messages
            )
            final_response = "".join([block.text for block in second_completion.content if block.type == "text"])
        else:
            final_response = "".join([block.text for block in completion.content if block.type == "text"])

        ai_response = {
            "response" : final_response,
            "source"   : "ai",
            "session_id": session_id,
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
        logger.error(f"Error handling AI ask request (Claude): {error_str}", exc_info=True)
        
        # Check for rate limit / quota exceeded (429)
        if "429" in error_str or "rate_limit" in error_str.lower() or "quota" in error_str.lower() or "overloaded" in error_str.lower():
            return {
                "error": "Claude API quota exceeded or rate limited. Please wait a moment and try again.",
                "status_code": 429,
                "details": error_str
            }
        
        return {
            "error": str(e),
            "status_code": 500
        }
