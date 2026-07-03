from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from fastapi.responses import HTMLResponse

from database.db import get_db
from database.models import Invoice
from core.billing import print_payload as PP

import os
from jinja2 import Environment, FileSystemLoader

router = APIRouter(tags=["public"])

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "core", "billing", "templates")
_jinja_env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR))

@router.get("/public/invoice/{uid_token}")
def get_public_invoice(
    uid_token: str,
    format: str = "json",
    db: Session = Depends(get_db)
):
    """
    Public share link for an invoice. 
    Requires NO authentication.
    Returns JSON payload or renders HTML/PDF based on query param or accept headers.
    """
    inv = db.query(Invoice).filter(Invoice.uid_token == uid_token).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found or link expired.")

    # Generate print payload (which excludes margins/cost prices inherently)
    payload = PP.build_print_payload(db, business_id=inv.business_id, invoice_no=inv.invoice_id)

    if format == "html" or format == "pdf":
        template_name = "invoice_classic_a4.html" 
        if inv.print_template == "thermal":
            template_name = "invoice_thermal.html"
            
        try:
            template = _jinja_env.get_template(template_name)
        except Exception:
            template = _jinja_env.get_template("invoice_classic_a4.html")
            
        html_content = template.render(payload=payload, **payload)
        
        if format == "pdf":
            try:
                import weasyprint
                pdf_bytes = weasyprint.HTML(string=html_content).write_pdf()
                from fastapi import Response
                return Response(
                    content=pdf_bytes,
                    media_type="application/pdf",
                    headers={
                        "Content-Disposition": f"inline; filename=invoice_{inv.invoice_id}.pdf"
                    }
                )
            except Exception:
                pass # fallback to HTML
        
        return HTMLResponse(content=html_content)

    # Return JSON by default
    return payload
