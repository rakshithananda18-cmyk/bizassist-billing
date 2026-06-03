import os
import json
import logging
from typing import Optional, Any
import numpy as np
from openai import OpenAI
from database.db import SessionLocal
from database.models import DocumentEmbedding, Invoice, Inventory, Payment

logger = logging.getLogger("bizassist.embeddings")

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
# INDEX SYNCHRONIZATION HELPERS
# ==========================================

def index_new_file_records(db, file_type: str, file_id: int, business_id: int):
    """
    Generates embeddings for all newly parsed records matching file_id
    and saves them to the document_embeddings database table.
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
        
        db.commit()
        logger.info(f"Successfully generated and committed {len(texts)} embeddings for file ID {file_id}.")
    except Exception as e:
        logger.error(f"Failed to generate embeddings for file ID {file_id}: {str(e)}", exc_info=True)
        # We catch exceptions so that a transient embeddings failure does not break the file upload transaction.

# ==========================================
# SEMANTIC VECTOR SEARCH
# ==========================================

def semantic_search_records(user_id: int, query: str, limit: int = 5) -> list:
    """
    Performs cosine-similarity vector search over all document embeddings
    for the specified user_id.
    """
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
