import logging
from fastapi import APIRouter, Depends, HTTPException
from database.db import SessionLocal
from database.models import ChatMessage
from services.auth import get_active_user
from sqlalchemy import func

router = APIRouter()
logger = logging.getLogger("bizassist.chat")


@router.get("/chat/sessions")
def get_chat_sessions(current_user: dict = Depends(get_active_user)):
    active_user_id = current_user["id"]
    logger.info(f"User {active_user_id} fetching list of chat sessions...")
    db = SessionLocal()
    try:
        # Query distinct sessions ordered by last active timestamp descending
        sessions = db.query(
            ChatMessage.session_id,
            ChatMessage.session_title,
            func.max(ChatMessage.timestamp).label("last_active")
        ).filter(
            ChatMessage.business_id == active_user_id
        ).group_by(
            ChatMessage.session_id,
            ChatMessage.session_title
        ).order_by(
            func.max(ChatMessage.timestamp).desc()
        ).all()

        result = []
        for s in sessions:
            if s.session_id:
                result.append({
                    "session_id": s.session_id,
                    "session_title": s.session_title or "Untitled Conversation",
                    "last_active": s.last_active.isoformat() if s.last_active else None
                })
        logger.info(f"Retrieved {len(result)} sessions for user {active_user_id}.")
        return result
    except Exception as e:
        logger.error(f"Error fetching chat sessions for user {active_user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch chat sessions")
    finally:
        db.close()


@router.get("/chat/history")
def get_chat_history(session_id: str = None, current_user: dict = Depends(get_active_user)):
    active_user_id = current_user["id"]
    logger.info(f"User {active_user_id} fetching session chat history for session_id={session_id}...")
    db = SessionLocal()
    try:
        query = db.query(ChatMessage).filter(ChatMessage.business_id == active_user_id)
        if session_id:
            query = query.filter(ChatMessage.session_id == session_id)
        else:
            # Fall back to latest active session_id if none specified
            latest_msg = db.query(ChatMessage).filter(
                ChatMessage.business_id == active_user_id
            ).order_by(ChatMessage.timestamp.desc()).first()
            if latest_msg and latest_msg.session_id:
                query = query.filter(ChatMessage.session_id == latest_msg.session_id)
            else:
                return [] # No history

        messages = query.order_by(ChatMessage.id.asc()).all()
        
        result = []
        for m in messages:
            result.append({
                "role": m.role,
                "content": m.content,
                "timestamp": m.timestamp.isoformat() if m.timestamp else None,
                "session_id": m.session_id,
                "session_title": m.session_title,
                "source": m.source,
                "model_tier": m.model_tier,
                "cached": bool(m.cached)
            })
        logger.info(f"Retrieved {len(result)} historical chat messages for user {active_user_id}.")
        return result
    except Exception as e:
        logger.error(f"Error fetching chat history for user {active_user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch chat history")
    finally:
        db.close()


@router.delete("/chat/history")
def delete_chat_history(session_id: str = None, current_user: dict = Depends(get_active_user)):
    active_user_id = current_user["id"]
    logger.warning(f"User {active_user_id} requested deletion of chat history for session_id={session_id}.")
    db = SessionLocal()
    try:
        query = db.query(ChatMessage).filter(ChatMessage.business_id == active_user_id)
        if session_id:
            query = query.filter(ChatMessage.session_id == session_id)
            deleted = query.delete()
        else:
            # Clear all conversations if no session specified
            deleted = query.delete()
            
        db.commit()
        logger.info(f"Successfully deleted {deleted} chat messages for user {active_user_id}.")
        
        # Sync deletion with Chroma persistent vector database
        try:
            from services.embeddings import delete_session_chroma_memories, delete_user_chroma_memories
            if session_id:
                delete_session_chroma_memories(session_id, active_user_id)
            else:
                delete_user_chroma_memories(active_user_id)
        except Exception as chroma_err:
            logger.error(f"Error purging Chroma memories: {chroma_err}", exc_info=True)

        # Also invalidate this user's query response cache (conversation history changed)
        from services.context_cache import invalidate_user_cache
        invalidate_user_cache(active_user_id)
        
        return {"message": "Chat history cleared", "deleted_count": deleted}
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting chat history for user {active_user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to clear chat history")
    finally:
        db.close()


# -------------------------------------------------
# RENAME CHAT SESSION TITLE
# -------------------------------------------------
from pydantic import BaseModel


class RenameSessionRequest(BaseModel):
    session_id: str
    title: str


@router.patch("/chat/session/title")
def rename_chat_session(req: RenameSessionRequest, current_user: dict = Depends(get_active_user)):
    active_user_id = current_user["id"]
    new_title = (req.title or "").strip()[:80]
    logger.info(f"User {active_user_id} renaming session {req.session_id} -> '{new_title}'")
    if not new_title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    db = SessionLocal()
    try:
        updated = db.query(ChatMessage).filter(
            ChatMessage.business_id == active_user_id,
            ChatMessage.session_id == req.session_id
        ).update({ChatMessage.session_title: new_title})
        db.commit()
        if updated == 0:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"message": "renamed", "session_id": req.session_id, "session_title": new_title}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error renaming chat session for user {active_user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to rename chat session")
    finally:
        db.close()
