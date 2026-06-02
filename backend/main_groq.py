import logging
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import Groq
from dotenv import load_dotenv
import os
import json

from routes.upload import router as upload_router
from routes.insights import router as insights_router
from routes.auth import router as auth_router
from routes.admin import router as admin_router
from database.db import engine
from database.models import Base

from services.query_router import classify
from services.direct_query_handler import handle as direct_handle
from services.context_cache import get_focused_context
from services.auth import get_active_user
from services.tools import execute_tool, schemas as tool_schemas
from database.migration import run_migrations_and_seed

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

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


class Prompt(BaseModel):
    message: str
    user_id: int = None


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

        # ── Layer 1: classify ────────────────────────────────────
        route, handler_key = classify(user_query)

        # ── Layer 2: direct DB answer ────────────────────────────
        if route == "DIRECT":
            answer = direct_handle(handler_key, user_query, active_user_id)

            if answer:
                logger.info(f"[BizAssist Router Decision] -> DIRECT/DB Path | Handler: {handler_key} | Query: '{user_query}'")
                return {
                    "response" : answer,
                    "source"   : "db",      # tells frontend: no AI token used
                }
            # If handler returned None (DB error), fall through to AI

        # ── Layer 2.5: check query response cache ────────────────
        from services.context_cache import get_cached_query_response, set_cached_query_response
        cached_response = get_cached_query_response(active_user_id, user_query)
        if cached_response:
            logger.info(f"[BizAssist Cache Hit] -> Returning cached AI response for query: '{user_query}'")
            cached_copy = cached_response.copy()
            cached_copy["cached"] = True
            return cached_copy

        # ── Layer 3: Groq with Tool Calling ──────────────────────
        logger.info(f"[BizAssist Router Decision] -> AI/Tool Calling Path | Query: '{user_query}'")
        system_prompt = (
            "You are BIZASSIST, an AI business intelligence assistant "
            "for Indian retail businesses (pharmacies, supermarkets, stores).\n\n"
            "Rules:\n"
            "- Answer using the database tools provided. Never invent numbers.\n"
            "- Use ₹ for Indian Rupees. Be specific: name customers, amounts.\n"
            "- Format lists with bullet points. Keep answers concise.\n"
            "- If the tools do not return data, state that clearly.\n"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_query},
        ]

        completion = client.chat.completions.create(
            messages=messages,
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            max_tokens=800,
            tools=tool_schemas,
            tool_choice="auto"
        )

        response_message = completion.choices[0].message
        tool_calls = response_message.tool_calls

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
                model="llama-3.3-70b-versatile",
                temperature=0.1,
                max_tokens=800
            )
            final_response = second_completion.choices[0].message.content
        else:
            final_response = response_message.content

        ai_response = {
            "response" : final_response,
            "source"   : "ai",
        }
        set_cached_query_response(active_user_id, user_query, ai_response)
        return ai_response

    except Exception as e:
        error_str = str(e)
        logger.error(f"Error handling AI ask request: {error_str}", exc_info=True)
        
        # Check for rate limit / quota exceeded (429)
        if "429" in error_str or "rate_limit" in error_str.lower() or "quota" in error_str.lower():
            return {
                "error": "API quota exceeded. Rate limit hit. Please wait a moment and try again.",
                "status_code": 429,
                "details": error_str
            }
        
        return {
            "error": str(e),
            "status_code": 500
        }