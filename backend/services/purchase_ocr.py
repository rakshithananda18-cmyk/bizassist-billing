import os
import json
import logging
import pypdf
import io
from groq import Groq
import anthropic
from PIL import Image

logger = logging.getLogger("bizassist.purchase_ocr")

_SCANNED_TEXT_THRESHOLD = 50


def parse_pdf_text(file_bytes: bytes) -> str:
    """Extracts raw text from PDF file bytes, falling back to OCR if digital text is scarce."""
    raw_text = _extract_digital_text(file_bytes)

    if len(raw_text.strip()) < _SCANNED_TEXT_THRESHOLD:
        logger.info(
            f"Digital extraction yielded only {len(raw_text.strip())} chars — "
            "treating as scanned PDF, running OCR fallback."
        )
        raw_text = _extract_ocr_text(file_bytes)

    return raw_text


def _extract_digital_text(file_bytes: bytes) -> str:
    """Fast path: extract embedded text from a digital PDF with pypdf."""
    raw_text = ""
    try:
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        logger.info(f"[Purchase PDF] Digital extraction — {len(reader.pages)} page(s).")
        for page in reader.pages:
            text = page.extract_text()
            if text:
                raw_text += text + "\n"
        logger.info(f"[Purchase PDF] Digital extraction yielded {len(raw_text)} chars.")
    except Exception as e:
        logger.warning(f"[Purchase PDF] pypdf extraction failed: {e}")
    return raw_text


def _extract_ocr_text(file_bytes: bytes) -> str:
    """OCR fallback for scanned PDFs."""
    try:
        from pdf2image import convert_from_bytes
        import pytesseract
    except ImportError as e:
        raise ValueError(
            f"OCR dependencies not installed ({e}). "
            "Run: pip install pdf2image pytesseract pillow"
        )

    try:
        logger.info("[Purchase PDF] Converting pages to images (300 dpi)…")
        pages = convert_from_bytes(file_bytes, dpi=300)
        logger.info(f"[Purchase PDF] {len(pages)} page(s) to OCR.")
    except Exception as e:
        raise ValueError(f"pdf2image conversion failed: {e}")

    try:
        available_langs = pytesseract.get_languages()
        lang = "eng+hin" if "hin" in available_langs else "eng"
    except Exception:
        lang = "eng"

    ocr_text = ""
    for i, page_img in enumerate(pages):
        try:
            text = pytesseract.image_to_string(page_img, lang=lang)
            ocr_text += text + "\n"
            logger.info(f"[Purchase PDF] Page {i+1}: {len(text)} chars extracted.")
        except Exception as e:
            logger.warning(f"[Purchase PDF] Page {i+1} OCR failed: {e}")

    logger.info(f"[Purchase PDF] Total OCR text: {len(ocr_text)} chars.")

    if len(ocr_text.strip()) < _SCANNED_TEXT_THRESHOLD:
        raise ValueError(
            "OCR could not extract readable text from this PDF. "
            "Check that the scan quality is sufficient."
        )

    return ocr_text


def _extract_image_text(file_bytes: bytes) -> str:
    """Extracts raw text from image bytes using pytesseract OCR."""
    try:
        import pytesseract
    except ImportError as e:
        raise ValueError("OCR dependencies not installed. Run: pip install pytesseract pillow")

    try:
        image = Image.open(io.BytesIO(file_bytes))
        try:
            available_langs = pytesseract.get_languages()
            lang = "eng+hin" if "hin" in available_langs else "eng"
        except Exception:
            lang = "eng"

        ocr_text = pytesseract.image_to_string(image, lang=lang)
        logger.info(f"[Purchase Image] OCR text: {len(ocr_text)} chars.")
        return ocr_text
    except Exception as e:
        raise ValueError(f"Image OCR extraction failed: {e}")


def extract_structured_purchase_invoice(raw_text: str) -> dict:
    """
    Sends raw supplier bill text to LLM (Groq, or Claude fallback chain)
    to output a JSON object adhering strictly to the purchase invoice schema.
    """
    system_prompt = (
        "You are a precise data extraction agent. Extract structured purchase invoice information "
        "from the provided raw supplier bill text. You must output a JSON object only. Do NOT output markdown code blocks (e.g. ```json), "
        "preamble, or explanations. The JSON output must strictly conform to the following schema:\n\n"
        "{\n"
        "  \"supplier_name\": \"string (name of the company/vendor selling the items)\",\n"
        "  \"invoice_number\": \"string (the supplier's invoice/bill number)\",\n"
        "  \"invoice_date\": \"string or null (format YYYY-MM-DD, e.g. 2026-05-12)\",\n"
        "  \"due_date\": \"string or null (format YYYY-MM-DD, or null)\",\n"
        "  \"notes\": \"string or null (any notes or terms on the bill)\",\n"
        "  \"gstin_buyer\": \"string or null (the buyer's GSTIN if mentioned)\",\n"
        "  \"place_of_supply\": \"string or null (GST place of supply state/code)\",\n"
        "  \"invoice_type\": \"string or null (B2B, B2C, Export, SEZ)\",\n"
        "  \"subtotal\": \"number (taxable value total across all items)\",\n"
        "  \"cgst_total\": \"number (CGST total)\",\n"
        "  \"sgst_total\": \"number (SGST total)\",\n"
        "  \"igst_total\": \"number (IGST total)\",\n"
        "  \"cess_total\": \"number (CESS total)\",\n"
        "  \"total_amount\": \"number (grand total invoice value)\",\n"
        "  \"reverse_charge\": \"boolean (true if reverse charge is applicable, default false)\",\n"
        "  \"is_tax_inclusive\": \"boolean (true if item prices include tax, default false)\",\n"
        "  \"discount_total\": \"number (invoice-level discount if any, default 0.0)\",\n"
        "  \"round_off\": \"number (round off adjustment, default 0.0)\",\n"
        "  \"items\": [\n"
        "    {\n"
        "      \"product_name\": \"string (name of the medicine, product, or line item)\",\n"
        "      \"hsn_sac\": \"string or null (HSN/SAC code)\",\n"
        "      \"unit\": \"string (e.g. Nos, Box, PCS, strip)\",\n"
        "      \"quantity\": \"number (quantity purchased)\",\n"
        "      \"purchase_unit\": \"string or null (unit in which purchased, if different, or null)\",\n"
        "      \"conversion_factor\": \"number (conversion factor to base unit, default 1.0)\",\n"
        "      \"unit_price\": \"number (rate per unit before tax)\",\n"
        "      \"cgst_rate\": \"number (CGST rate percentage, e.g. 9.0 or 6.0)\",\n"
        "      \"sgst_rate\": \"number (SGST rate percentage, e.g. 9.0 or 6.0)\",\n"
        "      \"igst_rate\": \"number (IGST rate percentage)\",\n"
        "      \"taxable_value\": \"number (taxable value for this line item)\",\n"
        "      \"cgst_amount\": \"number (CGST tax amount for this item)\",\n"
        "      \"sgst_amount\": \"number (SGST tax amount for this item)\",\n"
        "      \"igst_amount\": \"number (IGST tax amount for this item)\",\n"
        "      \"line_total\": \"number (total amount for this line including tax)\",\n"
        "      \"batch\": \"string or null (batch number if present, e.g. BT-908)\",\n"
        "      \"expiry\": \"string or null (expiry date format YYYY-MM-DD or MM/YY or similar)\"\n"
        "    }\n"
        "  ]\n"
        "}"
    )

    user_content = f"Raw Invoice Text:\n{raw_text}\n\nStrict JSON Output:"

    # 1. Try Groq (primary)
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        try:
            logger.info("Extracting purchase invoice using Groq (qwen/qwen3-32b)...")
            from services.groq_client import make_groq_client
            client = make_groq_client(groq_key)
            completion = client.chat.completions.create(
                model=os.getenv("GROQ_MODEL_COMPLEX", "qwen/qwen3-32b"),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            return json.loads(completion.choices[0].message.content)
        except Exception as e:
            logger.warning(f"Groq extraction failed: {str(e)}. Attempting fallback to Claude...")

    # 2. Fallback: Claude
    claude_key = os.getenv("CLAUDE_API_KEY")
    if claude_key:
        try:
            logger.info("Extracting purchase invoice using Anthropic (claude-3-5-sonnet-20241022)...")
            client = anthropic.Anthropic(api_key=claude_key)
            message = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=4000,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_content}
                ],
                temperature=0.0
            )
            response_text = message.content[0].text.strip()
            if response_text.startswith("```"):
                lines = response_text.splitlines()
                if lines[0].startswith("```json") or lines[0].startswith("```"):
                    lines = lines[1:-1]
                response_text = "\n".join(lines).strip()
            return json.loads(response_text)
        except Exception as e:
            logger.error(f"Anthropic extraction failed: {str(e)}")
            raise e

    raise ValueError("No configured LLM API keys (GROQ_API_KEY or CLAUDE_API_KEY) found for PDF extraction.")


def parse_purchase_file(file_bytes: bytes, filename: str) -> dict:
    """Parses a file (PDF or image) and extracts a structured purchase invoice JSON draft."""
    ext = os.path.splitext(filename.lower())[1]
    if ext == ".pdf":
        raw_text = parse_pdf_text(file_bytes)
    elif ext in [".png", ".jpg", ".jpeg", ".webp"]:
        raw_text = _extract_image_text(file_bytes)
    else:
        raise ValueError(f"Unsupported file type '{ext}'. Only PDFs and images are supported.")

    return extract_structured_purchase_invoice(raw_text)
