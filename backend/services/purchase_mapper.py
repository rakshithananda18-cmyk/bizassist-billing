import difflib
from sqlalchemy.orm import Session
from database.models import Product

def map_purchase_items_to_catalog(db: Session, business_id: int, extracted_items: list) -> list:
    """
    Fuzzy matches a list of extracted line items against the business's existing product catalog.
    
    Each item in extracted_items is a dictionary representing a PurchaseInvoiceLineItem.
    We enrich each item with:
      - product_id: ID of the matched Product (or None)
      - is_matched: Boolean indicating if it's a high-confidence match
      - confidence_score: Float representing matching ratio
      
    Returns the enriched list of items.
    """
    # Fetch all catalog products for the business
    catalog = db.query(Product).filter(Product.business_id == business_id).all()
    
    if not catalog:
        # No catalog products yet, so none can be matched
        for item in extracted_items:
            item["product_id"] = None
            item["is_matched"] = False
            item["confidence_score"] = 0.0
        return extracted_items

    for item in extracted_items:
        name = item.get("product_name", "").strip()
        if not name:
            item["product_id"] = None
            item["is_matched"] = False
            item["confidence_score"] = 0.0
            continue

        best_product = None
        best_ratio = 0.0

        for product in catalog:
            prod_name = product.name or ""
            ratio = difflib.SequenceMatcher(None, name.lower(), prod_name.lower()).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_product = product

        # Determine match quality based on confidence thresholds
        if best_ratio >= 0.8:
            item["product_id"] = best_product.id
            item["is_matched"] = True
            item["confidence_score"] = round(best_ratio, 3)
        elif best_ratio >= 0.5:
            # Low confidence match / suggestion
            item["product_id"] = best_product.id
            item["is_matched"] = False
            item["confidence_score"] = round(best_ratio, 3)
        else:
            item["product_id"] = None
            item["is_matched"] = False
            item["confidence_score"] = round(best_ratio, 3)

    return extracted_items
