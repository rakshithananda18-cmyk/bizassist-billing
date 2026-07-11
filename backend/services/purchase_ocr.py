import os
import io
import json
import base64
import logging
import pypdf
from groq import Groq
import anthropic
from PIL import Image

logger = logging.getLogger("bizassist.purchase_ocr")

_SCANNED_TEXT_THRESHOLD = 50

# One shared extraction schema/prompt, used by both the text path (PDF/OCR text
# → LLM) and the vision path (image → vision LLM).
_SYSTEM_PROMPT = (
    "You are a precise data extraction agent. Extract structured purchase invoice information "
    "from the provided supplier bill. You must output a JSON object only. Do NOT output markdown code blocks (e.g. ```json), "
    "preamble, or explanations. Read EVERY line item in the table carefully, column by column. "
    "The JSON output must strictly conform to the following schema:\n\n"
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
    """Extracts raw text from image bytes using pytesseract OCR (last-resort fallback)."""
    try:
        import pytesseract
    except ImportError:
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


# ── Vision path (image → structured JSON, no system OCR binary needed) ────────

def _mime_for(ext: str) -> str:
    return {
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp",
    }.get(ext.lstrip("."), "image/jpeg")


def _repair_json_with_llm(broken_json: str) -> str:
    """Uses a fast text LLM (Groq) to fix JSON syntax errors and return valid JSON."""
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        return ""
    try:
        from services.groq_client import make_groq_client
        client = make_groq_client(groq_key)
        model = os.getenv("GROQ_MODEL_SIMPLE", "llama3-8b-8192")
        logger.info(f"[Purchase Image] Attempting JSON repair using model {model}...")

        system_content = (
            "You are a JSON syntax repair assistant. Fix any syntax errors in the provided JSON string "
            "(such as missing commas, unmatched quotes, trailing commas, or misplaced delimiters) "
            "so that it forms perfectly valid JSON. Do not alter any key names, numeric values, or text content. "
            "Output ONLY the corrected valid JSON object. No markdown code blocks, no preamble, no explanation."
        )

        try:
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": broken_json}
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            repaired = completion.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"[Purchase Image] JSON repair with json_object format failed: {e}. Retrying without format parameter...")
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": broken_json}
                ],
                temperature=0.0,
            )
            repaired = completion.choices[0].message.content.strip()

        logger.info("[Purchase Image] JSON successfully repaired by LLM")
        return repaired
    except Exception as e:
        logger.warning(f"[Purchase Image] JSON LLM repair attempt failed: {e}")
        return ""


def _parse_json_loose(text: str) -> dict:
    """Parse a JSON object out of an LLM reply that may include code fences/prose."""
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError as jde:
        logger.warning(f"[Purchase Image] Initial JSON parse failed: {jde}. Attempting LLM syntax repair...")
        try:
            repaired_text = _repair_json_with_llm(text)
            if repaired_text:
                repaired_text = repaired_text.strip()
                if repaired_text.startswith("```"):
                    lines = repaired_text.splitlines()
                    if lines and lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    repaired_text = "\n".join(lines).strip()
                rstart, rend = repaired_text.find("{"), repaired_text.rfind("}")
                if rstart != -1 and rend != -1 and rend > rstart:
                    repaired_text = repaired_text[rstart:rend + 1]
                return json.loads(repaired_text)
        except Exception as re:
            logger.error(f"[Purchase Image] JSON repair failed or yielded invalid JSON: {re}")
        raise jde



def extract_purchase_from_image(file_bytes: bytes, ext: str) -> dict:
    """Send the image DIRECTLY to a vision LLM → structured invoice JSON.

    No pytesseract / Tesseract system binary required (fixes the "OCR
    dependencies not installed" error, incl. on the packaged Windows build),
    and far more accurate on angled phone photos than classic OCR.
    Tries Groq-vision → Gemini-vision → Claude-vision; raises if none succeed
    so the caller can fall back to Tesseract."""
    mime = _mime_for(ext)
    data_uri = f"data:{mime};base64,{base64.b64encode(file_bytes).decode()}"
    user_text = (
        "Extract this purchase/supplier invoice as strict JSON per the schema. "
        "Read every line item row from the table, column by column."
    )

    # 1) Groq vision (OpenAI-compatible chat with an image part)
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        try:
            from services.groq_client import make_groq_client
            client = make_groq_client(groq_key)
            completion = client.chat.completions.create(
                model=os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"),
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ]},
                ],
                temperature=0.0,
            )
            logger.info("[Purchase Image] extracted via Groq vision")
            return _parse_json_loose(completion.choices[0].message.content)
        except Exception as e:
            logger.warning(f"[Purchase Image] Groq vision failed: {e}")

    # 2) Gemini vision via its OpenAI-compatible endpoint (httpx, no new dep)
    gem_key = os.getenv("GEMINI_API_KEY")
    if gem_key:
        try:
            import httpx
            base = os.getenv(
                "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"
            ).rstrip("/")
            body = {
                "model": os.getenv("GEMINI_VISION_MODEL", "gemini-2.0-flash"),
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ]},
                ],
                "temperature": 0.0,
            }
            with httpx.Client(timeout=float(os.getenv("VISION_TIMEOUT_SECS", "90"))) as hc:
                r = hc.post(
                    f"{base}/chat/completions",
                    headers={"Authorization": f"Bearer {gem_key}", "Content-Type": "application/json"},
                    json=body,
                )
                r.raise_for_status()
                data = r.json()
            logger.info("[Purchase Image] extracted via Gemini vision")
            return _parse_json_loose(data["choices"][0]["message"]["content"])
        except Exception as e:
            logger.warning(f"[Purchase Image] Gemini vision failed: {e}")

    # 3) Claude vision
    claude_key = os.getenv("CLAUDE_API_KEY")
    if claude_key:
        try:
            client = anthropic.Anthropic(api_key=claude_key)
            message = client.messages.create(
                model=os.getenv("CLAUDE_VISION_MODEL", "claude-3-5-sonnet-20241022"),
                max_tokens=4000,
                temperature=0.0,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image", "source": {
                        "type": "base64", "media_type": mime,
                        "data": base64.b64encode(file_bytes).decode(),
                    }},
                ]}],
            )
            logger.info("[Purchase Image] extracted via Claude vision")
            return _parse_json_loose(message.content[0].text)
        except Exception as e:
            logger.warning(f"[Purchase Image] Claude vision failed: {e}")

    raise ValueError("No vision-capable LLM key available (GROQ/GEMINI/CLAUDE).")


def extract_structured_purchase_invoice(raw_text: str) -> dict:
    """Sends raw supplier bill TEXT to an LLM (Groq → Claude) → structured JSON."""
    user_content = f"Raw Invoice Text:\n{raw_text}\n\nStrict JSON Output:"

    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        try:
            logger.info("Extracting purchase invoice using Groq (qwen/qwen3-32b)...")
            from services.groq_client import make_groq_client
            client = make_groq_client(groq_key)
            completion = client.chat.completions.create(
                model=os.getenv("GROQ_MODEL_COMPLEX", "qwen/qwen3-32b"),
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            return _parse_json_loose(completion.choices[0].message.content)
        except Exception as e:
            logger.warning(f"Groq extraction failed: {str(e)}. Attempting fallback to Claude...")

    claude_key = os.getenv("CLAUDE_API_KEY")
    if claude_key:
        try:
            logger.info("Extracting purchase invoice using Anthropic (claude-3-5-sonnet-20241022)...")
            client = anthropic.Anthropic(api_key=claude_key)
            message = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=4000,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
                temperature=0.0,
            )
            return _parse_json_loose(message.content[0].text)
        except Exception as e:
            logger.error(f"Anthropic extraction failed: {str(e)}")
            raise e

    raise ValueError("No configured LLM API keys (GROQ_API_KEY or CLAUDE_API_KEY) found for extraction.")


def parse_purchase_file(file_bytes: bytes, filename: str) -> dict:
    """Parses a file (PDF or image) and extracts a structured purchase invoice JSON draft."""
    ext = os.path.splitext(filename.lower())[1]
    if ext == ".pdf":
        raw_text = parse_pdf_text(file_bytes)
        return extract_structured_purchase_invoice(raw_text)

    if ext in [".png", ".jpg", ".jpeg", ".webp"]:
        # Prefer the vision LLM (no system OCR binary, better on photos). Falls
        # back to Tesseract only if vision is disabled or every provider fails.
        if os.getenv("PURCHASE_OCR_VISION", "1") != "0":
            try:
                return extract_purchase_from_image(file_bytes, ext)
            except Exception as e:
                logger.warning(f"[Purchase Image] vision path failed ({e}); falling back to Tesseract OCR.")
        raw_text = _extract_image_text(file_bytes)
        return extract_structured_purchase_invoice(raw_text)

    raise ValueError(f"Unsupported file type '{ext}'. Only PDFs and images are supported.")
