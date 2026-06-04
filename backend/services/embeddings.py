import os
import json
import logging
import time
from datetime import datetime
from typing import Optional, Any
import numpy as np
from openai import OpenAI
import chromadb
from database.db import SessionLocal
from database.models import DocumentEmbedding, Invoice, Inventory, Payment

logger = logging.getLogger("bizassist.embeddings")

CHROMA_DB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "chroma_db"))
_chroma_client = None

def get_chroma_client():
    global _chroma_client
    if _chroma_client is None:
        try:
            os.makedirs(CHROMA_DB_DIR, exist_ok=True)
            _chroma_client = chromadb.PersistentClient(path=CHROMA_DB_DIR)
            logger.info(f"[Chroma] Initialized persistent client at {CHROMA_DB_DIR}")
        except Exception as e:
            logger.error(f"[Chroma] Failed to initialize persistent client: {e}", exc_info=True)
            raise e
    return _chroma_client

def get_chat_memory_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(name="chat_history_memory")

def get_document_embeddings_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(name="document_embeddings")

def get_openai_client() -> Optional[OpenAI]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY environment variable is not set!")
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {e}")
        return None

def generate_embedding(text: str) -> list:
    """Generates embedding for a single text input using text-embedding-3-small."""
    client = get_openai_client()
    if not client:
        raise ValueError("OpenAI client not configured or API key missing.")
    
    response = client.embeddings.create(
        input=text,
        model="text-embedding-3-small"
    )
    return response.data[0].embedding

def generate_embeddings_batch(texts: list) -> list:
    """Generates embeddings for a list of text inputs in a single batch."""
    if not texts:
        return []
    client = get_openai_client()
    if not client:
        raise ValueError("OpenAI client not configured or API key missing.")
    
    response = client.embeddings.create(
        input=texts,
        model="text-embedding-3-small"
    )
    return [item.embedding for item in response.data]

# ==========================================
# TEXT SERIALIZATION HELPERS
# ==========================================

def make_invoice_text(inv: Invoice) -> str:
    amount_str = f"₹{inv.amount:,.2f}" if inv.amount is not None else "₹0.00"
    return (
        f"Invoice record. Invoice ID: {inv.invoice_id or 'N/A'}. "
        f"Customer: {inv.customer or 'N/A'}. "
        f"Amount: {amount_str}. "
        f"Status: {inv.status or 'N/A'}. "
        f"Invoice Date: {inv.invoice_date or 'N/A'}. "
        f"Due Date: {inv.due_date or 'N/A'}."
    )

def make_inventory_text(item: Inventory) -> str:
    stock_status = "Low stock!" if (item.stock is not None and item.stock <= 10) else "In stock"
    return (
        f"Inventory item. Product Name: {item.product_name or 'N/A'}. "
        f"Stock Level: {item.stock if item.stock is not None else 0} units ({stock_status}). "
        f"Expiry Date: {item.expiry_date or 'N/A'}. "
        f"Supplier: {item.supplier or 'N/A'}."
    )

def make_payment_text(pmt: Payment) -> str:
    amount_str = f"₹{pmt.amount:,.2f}" if pmt.amount is not None else "₹0.00"
    paid_status = "Paid" if (pmt.paid and pmt.paid.lower() == "yes") else "Unpaid/Pending"
    return (
        f"Payment transaction details. Customer: {pmt.customer or 'N/A'}. "
        f"Amount: {amount_str}. "
        f"Status: {paid_status} (Paid value: {pmt.paid or 'N/A'}). "
        f"Due Date: {pmt.due_date or 'N/A'}."
    )

# ==========================================
# CHROMA CHAT MEMORY HELPERS
# ==========================================

def save_chat_memory(business_id: int, session_id: str, session_title: str, user_query: str, assistant_response: str):
    """
    Saves a QA conversation turn to Chroma vector database for semantic retrieval.
    """
    try:
        collection = get_chat_memory_collection()
        embedding = generate_embedding(user_query)
        doc_id = f"chat_{business_id}_{session_id}_{int(time.time())}_{np.random.randint(1000, 9999)}"
        
        collection.add(
            ids=[doc_id],
            embeddings=[embedding],
            metadatas=[{
                "business_id": int(business_id),
                "session_id": str(session_id),
                "session_title": str(session_title or "Untitled Conversation"),
                "user_query": str(user_query),
                "assistant_response": str(assistant_response),
                "timestamp": datetime.utcnow().isoformat()
            }],
            documents=[user_query]
        )
        logger.info(f"[Chroma Memory] Saved chat turn for user {business_id}, session {session_id}")
    except Exception as e:
        logger.error(f"[Chroma Memory] Failed to save chat memory: {e}", exc_info=True)

def search_chat_memories(business_id: int, query: str, limit: int = 3) -> str:
    """
    Searches Chroma for semantically similar previous queries by this user,
    returning a formatted context block.
    """
    try:
        collection = get_chat_memory_collection()
        query_vector = generate_embedding(query)
        
        # Query Chroma, filtering by business_id to ensure strict tenant isolation
        results = collection.query(
            query_embeddings=[query_vector],
            n_results=limit,
            where={"business_id": int(business_id)}
        )
        
        if not results or not results.get("metadatas") or not results["metadatas"][0]:
            return ""
            
        memories = []
        metadatas = results["metadatas"][0]
        distances = results["distances"][0] if "distances" in results else [0.0] * len(metadatas)
        
        for meta, dist in zip(metadatas, distances):
            # Cosine distance in Chroma: lower is more similar.
            # A distance <= 0.8 is typical for relevance threshold.
            if dist <= 0.8:
                memories.append(
                    f"User asked: '{meta['user_query']}'\nAssistant responded: '{meta['assistant_response']}'"
                )
                
        if memories:
            context_block = "\n=== RELEVANT PAST CONVERSATIONS (MEMORY) ===\n"
            context_block += "\n---\n".join(memories)
            context_block += "\n============================================\n"
            return context_block
            
        return ""
    except Exception as e:
        logger.error(f"[Chroma Memory] Failed to query chat memories: {e}", exc_info=True)
        return ""

def delete_user_chroma_memories(business_id: int):
    """Purges all chat memories and document embeddings for a target business_id."""
    try:
        # Delete chat memory
        chat_collection = get_chat_memory_collection()
        chat_collection.delete(where={"business_id": int(business_id)})
        logger.info(f"[Chroma Memory] Purged all chat memories for user {business_id}")
        
        # Delete document embeddings
        doc_collection = get_document_embeddings_collection()
        doc_collection.delete(where={"business_id": int(business_id)})
        logger.info(f"[Chroma Document] Purged all document embeddings for user {business_id}")
    except Exception as e:
        logger.error(f"[Chroma] Failed to purge user memories/embeddings: {e}", exc_info=True)

def delete_session_chroma_memories(session_id: str, business_id: int):
    """Purges all chat memories for a specific session_id."""
    try:
        collection = get_chat_memory_collection()
        # Chroma allows multi-key metadata filters inside logical blocks
        collection.delete(
            where={
                "$and": [
                    {"session_id": str(session_id)},
                    {"business_id": int(business_id)}
                ]
            }
        )
        logger.info(f"[Chroma Memory] Purged chat memories for session {session_id}, user {business_id}")
    except Exception as e:
        logger.error(f"[Chroma Memory] Failed to delete session memories: {e}", exc_info=True)

def delete_file_chroma_embeddings(file_id: int, business_id: int):
    """Purges document embeddings associated with a parsed file using file_user_key."""
    try:
        collection = get_document_embeddings_collection()
        file_user_key = f"{file_id}_{business_id}"
        collection.delete(where={"file_user_key": file_user_key})
        logger.info(f"[Chroma Document] Purged embeddings for file {file_id}, user {business_id}")
    except Exception as e:
        logger.error(f"[Chroma Document] Failed to delete file embeddings: {e}", exc_info=True)

# ==========================================
# INDEX SYNCHRONIZATION HELPERS
# ==========================================

def index_new_file_records(db, file_type: str, file_id: int, business_id: int):
    """
    Generates embeddings for all newly parsed records matching file_id
    and saves them to the document_embeddings database table and Chroma.
    """
    try:
        logger.info(f"Indexing embeddings for file ID {file_id} (Type: {file_type}) for user {business_id}...")
        records = []
        if file_type == "invoice":
            records = db.query(Invoice).filter(Invoice.file_id == file_id, Invoice.business_id == business_id).all()
        elif file_type == "inventory":
            records = db.query(Inventory).filter(Inventory.file_id == file_id, Inventory.business_id == business_id).all()
        elif file_type == "payment":
            records = db.query(Payment).filter(Payment.file_id == file_id, Payment.business_id == business_id).all()

        if not records:
            logger.info(f"No records found for file ID {file_id}. Skipping embedding generation.")
            return

        texts = []
        record_ids = []
        
        for r in records:
            if file_type == "invoice":
                texts.append(make_invoice_text(r))
            elif file_type == "inventory":
                texts.append(make_inventory_text(r))
            elif file_type == "payment":
                texts.append(make_payment_text(r))
            record_ids.append(r.id)

        # Batch text embeddings (batch size of 100 to avoid OpenAI payload limits)
        batch_size = 100
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i+batch_size]
            batch_ids = record_ids[i:i+batch_size]
            
            logger.info(f"Generating embeddings batch {i // batch_size + 1} ({len(batch_texts)} items)...")
            embeddings = generate_embeddings_batch(batch_texts)

            # 1. Save to SQLite DocumentEmbedding table
            for text_content, rec_id, emb in zip(batch_texts, batch_ids, embeddings):
                db_emb = DocumentEmbedding(
                    business_id=business_id,
                    file_id=file_id,
                    document_type=file_type,
                    record_id=rec_id,
                    text_content=text_content,
                    embedding_json=json.dumps(emb)
                )
                db.add(db_emb)

            # 2. Save to Chroma DB Collection
            try:
                doc_collection = get_document_embeddings_collection()
                chroma_ids = [f"doc_{business_id}_{file_type}_{rid}" for rid in batch_ids]
                chroma_metadatas = [{
                    "business_id": int(business_id),
                    "file_id": int(file_id),
                    "file_user_key": f"{file_id}_{business_id}",
                    "document_type": str(file_type),
                    "record_id": int(rid),
                    "text_content": str(txt)
                } for rid, txt in zip(batch_ids, batch_texts)]
                
                doc_collection.add(
                    ids=chroma_ids,
                    embeddings=embeddings,
                    metadatas=chroma_metadatas,
                    documents=batch_texts
                )
                logger.info(f"[Chroma Document] Indexed {len(batch_texts)} items in Chroma for file ID {file_id}")
            except Exception as chroma_err:
                logger.error(f"[Chroma Document] Failed parallel indexing to Chroma: {chroma_err}", exc_info=True)
        
        db.commit()
        logger.info(f"Successfully generated and committed {len(texts)} embeddings for file ID {file_id}.")
    except Exception as e:
        logger.error(f"Failed to generate embeddings for file ID {file_id}: {str(e)}", exc_info=True)

# ==========================================
# SEMANTIC VECTOR SEARCH
# ==========================================

def semantic_search_records(user_id: int, query: str, limit: int = 5) -> list:
    """
    Performs vector search over document embeddings.
    First queries Chroma for performance; falls back to SQLite brute-force if Chroma fails or is empty.
    """
    # ── Try Chroma first ──────────────────────────────────────────
    try:
        doc_collection = get_document_embeddings_collection()
        query_vector = generate_embedding(query)
        
        results = doc_collection.query(
            query_embeddings=[query_vector],
            n_results=limit,
            where={"business_id": int(user_id)}
        )
        
        if results and results.get("ids") and results["ids"][0]:
            logger.info(f"[Chroma Document] Query successful. Found {len(results['ids'][0])} records.")
            output = []
            ids = results["ids"][0]
            metadatas = results["metadatas"][0]
            distances = results["distances"][0] if "distances" in results else [0.0] * len(metadatas)
            
            for rid, meta, dist in zip(ids, metadatas, distances):
                # Score: convert L2/cosine distance to similarity score
                similarity = 1.0 - float(dist)
                output.append({
                    "score": similarity,
                    "document_type": meta["document_type"],
                    "record_id": meta["record_id"],
                    "text_content": meta["text_content"]
                })
                logger.info(f"Match (Chroma): Score={similarity:.4f} | Type={meta['document_type']} | Content={meta['text_content']}")
            return output
            
        logger.info(f"[Chroma Document] No matches in Chroma for user {user_id}. Falling back to SQLite.")
    except Exception as chroma_err:
        logger.error(f"[Chroma Document] Search failed, falling back to SQLite: {chroma_err}")

    # ── Fallback: SQLite brute-force ──────────────────────────────
    db = SessionLocal()
    try:
        # Load all embeddings for this user
        db_embeddings = db.query(DocumentEmbedding).filter(DocumentEmbedding.business_id == user_id).all()
        if not db_embeddings:
            logger.info(f"No embeddings indexed for user {user_id}. Returning empty search.")
            return []

        logger.info(f"Computing semantic similarity for query '{query}' across {len(db_embeddings)} records...")
        
        # Generate query embedding
        query_vector = np.array(generate_embedding(query), dtype=np.float32)

        # Extract doc vectors and compute cosine similarities
        doc_vectors = []
        doc_metadata = []
        for doc in db_embeddings:
            try:
                vec = json.loads(doc.embedding_json)
                doc_vectors.append(vec)
                doc_metadata.append({
                    "id": doc.id,
                    "document_type": doc.document_type,
                    "record_id": doc.record_id,
                    "text_content": doc.text_content
                })
            except Exception as parse_err:
                logger.error(f"Failed parsing embedding JSON for doc ID {doc.id}: {parse_err}")

        if not doc_vectors:
            return []

        doc_matrix = np.array(doc_vectors, dtype=np.float32) # Matrix shape: (N, D)

        # Vectorized Cosine Similarity Calculation
        # CosSim(A, B) = A . B / (||A|| * ||B||)
        dot_products = np.dot(doc_matrix, query_vector) # Shape: (N,)
        query_norm = np.linalg.norm(query_vector)
        doc_norms = np.linalg.norm(doc_matrix, axis=1) # Shape: (N,)
        
        # Avoid division by zero
        doc_norms = np.where(doc_norms == 0, 1e-9, doc_norms)

        similarities = dot_products / (query_norm * doc_norms)

        # Rank results
        top_indices = np.argsort(similarities)[::-1][:limit]

        results = []
        for idx in top_indices:
            score = float(similarities[idx])
            meta = doc_metadata[idx]
            results.append({
                "score": score,
                "document_type": meta["document_type"],
                "record_id": meta["record_id"],
                "text_content": meta["text_content"]
            })
            logger.info(f"Match: Score={score:.4f} | Type={meta['document_type']} | Content={meta['text_content']}")

        return results
    except Exception as e:
        logger.error(f"Semantic search failed: {str(e)}", exc_info=True)
        return [{"error": f"Semantic search failed: {str(e)}"}]
    finally:
        db.close()
