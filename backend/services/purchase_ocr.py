import os
import io
import json
import base64
import logging
import pypdf
from groq import Groq
from PIL import Image

logger = logging.getLogger("bizassist.purchase_ocr")

# ── Stop asking for a model this key cannot have ─────────────────────────────
# Vision is an OPTIMISATION, not a requirement: a photo can always go
# image → Tesseract → text → Groq text model, which is the same destination the
# vision path reaches in one hop. So when the vision model is refused, the right
# move is to stop trying, not to fail the upload.
#
# Observed 2026-08-07: `meta-llama/llama-4-scout-17b-16e-instruct` returns 404
# "does not exist or you do not have access to it" for a key that authenticates
# fine. That is an entitlement, and no number of retries changes it — but every
# bill scanned paid a full round trip to discover it again before falling back.
#
# Same shape as `_SELF_SIGNED_REJECTED` in services/sync_worker.py: a failure
# that cannot self-heal is remembered, so it costs one call rather than one per
# request. In-process, so a restart re-checks — if the account gains vision
# access, it resumes on its own with nothing to configure.
_VISION_UNAVAILABLE = False


def _note_vision_failure(e: Exception) -> None:
    """Latch OFF only for refusals that are permanent for this key.

    A 429 or a timeout is the model being busy — retry those. A 404/403 on the
    MODEL is the account not having it, which will read exactly the same on
    every future upload.
    """
    global _VISION_UNAVAILABLE
    msg = str(e).lower()
    permanent = ("model_not_found" in msg
                 or "does not exist or you do not have access" in msg
                 or ("404" in msg and "model" in msg)
                 or "403" in msg)
    if permanent and not _VISION_UNAVAILABLE:
        _VISION_UNAVAILABLE = True
        # GROQ-specific, despite the global name. Since Gemini vision was
        # restored (2026-08-08) this latch no longer means "vision is off" — it
        # means "stop paying a round trip to rediscover that GROQ has no vision
        # model on this key". Gemini is tried next and normally answers. Saying
        # "bill scanning continues via Tesseract" here was simply untrue once a
        # second provider existed, and would send someone installing binaries
        # they do not need.
        logger.warning(
            "[Purchase Image] GROQ has no vision model for this API key (%s). "
            "Skipping Groq vision for the rest of this process; the next vision "
            "provider is tried as normal. To use Groq for vision, grant the key "
            "a vision model or set GROQ_VISION_MODEL, then restart.",
            str(e)[:160],
        )

_SCANNED_TEXT_THRESHOLD = 50

# One shared extraction schema/prompt, used by both the text path (PDF/OCR text
# → LLM) and the vision path (image → vision LLM).
_SYSTEM_PROMPT = (
    "You are a precise data extraction agent. Extract structured purchase invoice information "
    "from the provided supplier bill. You must output a JSON object only. Do NOT output markdown code blocks (e.g. ```json), "
    "preamble, or explanations. Read EVERY line item in the table carefully, column by column. "
    "IMPORTANT: You must carefully distinguish between the Supplier/Seller (the entity selling the goods, e.g., 'SRI TIRUMALA VENKATESWARA AG') and the Buyer (the entity purchasing the goods, e.g., 'M R TRADERS'). Do NOT extract the buyer's name, buyer's GSTIN, buyer's PAN, or buyer's address into the supplier fields. The supplier fields must strictly contain the seller's information. "
    "The JSON output must strictly conform to the following schema:\n\n"
    "{\n"
    "  \"supplier_name\": \"string (name of the company/vendor selling the items)\",\n"
    "  \"supplier_gstin\": \"string or null (the supplier's GSTIN/GST number if present)\",\n"
    "  \"supplier_pan\": \"string or null (the supplier's PAN card number if present)\",\n"
    "  \"supplier_fssai\": \"string or null (the supplier's FSSAI license number if present)\",\n"
    "  \"supplier_phone\": \"string or null (the supplier's phone number if present)\",\n"
    "  \"supplier_address\": \"string or null (the supplier's address/location if present)\",\n"
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

    # `pytesseract` is a WRAPPER. It imports cleanly with no OCR engine present,
    # so the guard above cannot catch a deployment that lacks the binary — which
    # is exactly the shape the cloud image had, and the owner was told to pip
    # install packages that were already installed. Check for the engine itself.
    try:
        pytesseract.get_tesseract_version()
    except Exception:
        raise ValueError(
            "The Tesseract OCR engine is not installed on this server, so a "
            "photo of a bill cannot be read here. Reading images normally uses "
            "the AI vision model instead — this fallback only runs when that is "
            "unavailable, so check the AI provider key first."
        )

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

# Pinned deliberately — see the measurement table in _extract_via_vision.
DEFAULT_GEMINI_VISION_MODEL = "gemini-3.1-flash-lite"


def _mime_for(ext: str) -> str:
    return {
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp",
        # Gemini accepts a PDF on the same endpoint as an image, so a SCANNED
        # pdf (no embedded text) can go straight to vision instead of needing
        # poppler to rasterise it and Tesseract to read it. Measured 2026-08-08:
        # an image-only PDF that pypdf read 0 characters from extracted
        # completely in 4.9 s / 3,101 tokens.
        "pdf": "application/pdf",
    }.get(ext.lstrip("."), "image/jpeg")


def _repair_json_with_llm(broken_json: str) -> str:
    """Uses a fast text LLM (Groq) to fix JSON syntax errors and return valid JSON."""
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        return ""
    try:
        from services.groq_client import DEFAULT_TEXT_MODEL, make_groq_client
        client = make_groq_client(groq_key)
        model = os.getenv("GROQ_MODEL_SIMPLE", DEFAULT_TEXT_MODEL)
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
    Tries Groq-vision → Gemini-vision; raises if both fail so the caller can
    fall back to Tesseract. (Claude was removed with the other providers and its
    key has no credit; Groq has no vision model on this account at all, so in
    practice Gemini is the one that answers.)"""
    # Why a provider failed, so the final error can say it. A swallowed
    # provider error plus a "no key available" message sent the owner
    # hunting for a key that was already set.
    provider_errors: list[str] = []
    mime = _mime_for(ext)
    data_uri = f"data:{mime};base64,{base64.b64encode(file_bytes).decode()}"
    user_text = (
        "Extract this purchase/supplier invoice as strict JSON per the schema. "
        "Read every line item row from the table, column by column."
    )

    # 1) Groq vision (OpenAI-compatible chat with an image part)
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key and not _VISION_UNAVAILABLE:
        try:
            from services.groq_client import DEFAULT_VISION_MODEL, make_groq_client
            client = make_groq_client(groq_key)
            completion = client.chat.completions.create(
                model=os.getenv("GROQ_VISION_MODEL", DEFAULT_VISION_MODEL),
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
            _note_vision_failure(e)
            logger.warning(f"[Purchase Image] Groq vision failed: {e}")
            provider_errors.append(f"Groq: {e}")
    # 2) Gemini vision — RESTORED 2026-08-08.
    #
    # This block was deleted by 83f13b1 ("Groq is the only provider"). That was
    # the right call for TEXT — Groq serves it fine — but it removed the only
    # working vision path, because Groq has never had a vision model on this
    # key: `models.list()` returns 15 entries and not one is vision-capable,
    # which is why DEFAULT_VISION_MODEL 404s with "does not exist or you do not
    # have access to it".
    #
    # Model choice is measured, not assumed (2026-08-08, one synthetic supplier
    # invoice scored field-by-field against known ground truth):
    #
    #   gemini-3.1-flash-lite    4.1 s   3,635 tok   28/28   <- pinned
    #   gemini-3.5-flash-lite    4.2 s   3,645 tok   28/28
    #   gemini-3.6-flash        22.5 s   8,244 tok   28/28   (5.5x slower, same score)
    #   gemini-3-flash-preview  53.8 s  18,117 tok   truncated at 16k
    #   gemini-2.0-flash-lite      free-tier limit 0 — NOT free
    #
    # PINNED, not `gemini-flash-latest`. The only reason the July regression was
    # diagnosable is that the old code pinned `gemini-2.0-flash` and we could
    # see it had lost its free tier (429, `limit: 0`). An alias would have moved
    # silently. This repo has already been bitten twice by model churn —
    # d2f2ff3 and 9985ce1 are both "replace decommissioned model" commits.
    gem_key = os.getenv("GEMINI_API_KEY")
    if gem_key:
        try:
            import httpx
            base = os.getenv("GEMINI_BASE_URL",
                             "https://generativelanguage.googleapis.com/v1beta/openai")
            payload = {
                "model": os.getenv("GEMINI_VISION_MODEL", DEFAULT_GEMINI_VISION_MODEL),
                "temperature": 0.0,
                # Generous: the reasoning-heavy models blow past a small cap and
                # return an UNTERMINATED string, which reads as a parse bug
                # rather than truncation. finish_reason is checked below.
                "max_tokens": int(os.getenv("VISION_MAX_TOKENS", "16000")),
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ]},
                ],
            }
            with httpx.Client(timeout=float(os.getenv("VISION_TIMEOUT_SECS", "90"))) as hc:
                r = hc.post(f"{base}/chat/completions", json=payload,
                            headers={"Authorization": f"Bearer {gem_key}"})
                r.raise_for_status()
                body = r.json()
            choice = body["choices"][0]
            if choice.get("finish_reason") == "length":
                # Say so rather than letting _parse_json_loose report a syntax
                # error for what is really a budget stop.
                raise ValueError(
                    "Gemini hit the output token limit before finishing the JSON — "
                    "raise VISION_MAX_TOKENS or use a less verbose model.")
            logger.info("[Purchase Image] extracted via Gemini vision")
            return _parse_json_loose(choice["message"]["content"])
        except Exception as e:
            logger.warning(f"[Purchase Image] Gemini vision failed: {e}")
            provider_errors.append(f"Gemini: {e}")

    if _VISION_UNAVAILABLE:
        # Skipped, not silent: the caller falls through to Tesseract, and the
        # reason is on the record so nobody hunts for a vision bug that is
        # actually an account entitlement.
        provider_errors.append(
            "Groq vision: skipped — this key has no access to any vision model "
            "(see the earlier log line)."
        )

    if provider_errors:
        raise ValueError(
            "The AI vision model could not read this image: " + "; ".join(provider_errors)
        )
    raise ValueError(
        "Bill scanning needs a vision-capable provider: either GEMINI_API_KEY, "
        "or a GROQ key with access to a vision model."
    )



def extract_structured_purchase_invoice(raw_text: str) -> dict:
    """Sends raw supplier bill TEXT to an LLM (Groq → Claude) → structured JSON."""
    user_content = f"Raw Invoice Text:\n{raw_text}\n\nStrict JSON Output:"

    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        try:
            from services.groq_client import DEFAULT_COMPLEX_MODEL, make_groq_client
            model = os.getenv("GROQ_MODEL_COMPLEX", DEFAULT_COMPLEX_MODEL)
            logger.info("Extracting purchase invoice using Groq (%s)...", model)
            client = make_groq_client(groq_key)
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            return _parse_json_loose(completion.choices[0].message.content)
        except Exception as e:
            # Groq is the only provider. Re-raise rather than logging "attempting
            # fallback to Claude" and then falling through to a bare ValueError —
            # that message described a path that no longer exists and buried the
            # real cause.
            logger.error(f"Groq extraction failed: {e}")
            raise

    raise ValueError("Bill scanning needs GROQ_API_KEY to be configured.")


def parse_purchase_file(file_bytes: bytes, filename: str) -> dict:
    """Parses a file (PDF or image) and extracts a structured purchase invoice JSON draft."""
    ext = os.path.splitext(filename.lower())[1]
    if ext == ".pdf":
        # DIGITAL first: pypdf reads embedded text with no model call, no network
        # and no system binary. Cheapest correct answer wins.
        raw_text = _extract_digital_text(file_bytes)
        if len(raw_text.strip()) >= _SCANNED_TEXT_THRESHOLD:
            return extract_structured_purchase_invoice(raw_text)

        # SCANNED (pypdf found nothing) — send the PDF to vision AS A PDF.
        # Gemini accepts application/pdf on the same endpoint as an image, so
        # this needs neither poppler (to rasterise) nor Tesseract (to read),
        # neither of which is installed. Measured 2026-08-08 on an image-only
        # PDF that pypdf read 0 chars from: complete extraction, 4.9 s.
        logger.info(
            "[Purchase PDF] only %d chars of embedded text — treating as scanned "
            "and sending the PDF to vision.", len(raw_text.strip()))
        vision_error = None
        if os.getenv("PURCHASE_OCR_VISION", "1") != "0":
            try:
                return extract_purchase_from_image(file_bytes, ".pdf")
            except Exception as e:
                vision_error = e
                logger.warning(
                    "[Purchase PDF] vision path failed (%s); falling back to "
                    "poppler+Tesseract OCR.", e)
        try:
            return extract_structured_purchase_invoice(_extract_ocr_text(file_bytes))
        except Exception as ocr_error:
            # Report the reason the PREFERRED path was abandoned, not just the
            # last thing tried — the fallback's own message describes missing
            # binaries and hides that vision is the actual cause.
            if vision_error is not None:
                raise ValueError(
                    f"Could not read this PDF. It has no embedded text, the AI "
                    f"vision model failed ({vision_error}), and the offline OCR "
                    f"fallback is also unavailable ({ocr_error})."
                ) from ocr_error
            raise

    if ext in [".png", ".jpg", ".jpeg", ".webp"]:
        # Prefer the vision LLM (no system OCR binary, better on photos). Falls
        # back to Tesseract only if vision is disabled or every provider fails.
        vision_error = None
        if os.getenv("PURCHASE_OCR_VISION", "1") != "0":
            try:
                return extract_purchase_from_image(file_bytes, ext)
            except Exception as e:
                vision_error = e
                logger.warning(f"[Purchase Image] vision path failed ({e}); falling back to Tesseract OCR.")
        try:
            raw_text = _extract_image_text(file_bytes)
        except Exception as ocr_error:
            # BOTH paths failed. The fallback's message alone is misleading: it
            # describes the last thing tried, not the reason the preferred path
            # was abandoned — and vision failing (no provider key, provider
            # outage) is the actual cause. Report the real one.
            if vision_error is not None:
                raise ValueError(
                    f"Could not read this image. The AI vision model failed "
                    f"({vision_error}), and the offline OCR fallback is also "
                    f"unavailable ({ocr_error})."
                ) from ocr_error
            raise
        return extract_structured_purchase_invoice(raw_text)

    raise ValueError(f"Unsupported file type '{ext}'. Only PDFs and images are supported.")
