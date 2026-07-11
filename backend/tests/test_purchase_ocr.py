import os
import sys
from unittest.mock import MagicMock, patch

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"

# Mock missing OCR dependencies in sys.modules before imports occur
import importlib.machinery
mock_pdf2image = MagicMock()
mock_pytesseract = MagicMock()
mock_pdf2image.__spec__ = importlib.machinery.ModuleSpec("pdf2image", None)
mock_pytesseract.__spec__ = importlib.machinery.ModuleSpec("pytesseract", None)
sys.modules["pdf2image"] = mock_pdf2image
sys.modules["pytesseract"] = mock_pytesseract

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest

@pytest.fixture(scope="module", autouse=True)
def cleanup_sys_modules():
    yield
    sys.modules.pop("pdf2image", None)
    sys.modules.pop("pytesseract", None)

from services.purchase_ocr import (
    parse_pdf_text,
    _extract_digital_text,
    _extract_ocr_text,
    _extract_image_text,
    extract_structured_purchase_invoice,
    parse_purchase_file
)

# ── Mocking PDF extraction ───────────────────────────────────────────────────

def test_extract_digital_text_success():
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Digital PDF Content"
    
    mock_reader = MagicMock()
    mock_reader.pages = [mock_page]
    
    with patch("pypdf.PdfReader", return_value=mock_reader):
        text = _extract_digital_text(b"mock pdf bytes")
        assert "Digital PDF Content" in text

def test_extract_digital_text_failure_returns_empty():
    with patch("pypdf.PdfReader", side_effect=Exception("Read error")):
        text = _extract_digital_text(b"corrupted pdf bytes")
        assert text == ""

def test_parse_pdf_text_prefers_digital():
    # If character count is above threshold, do not fall back to OCR
    with patch("services.purchase_ocr._extract_digital_text", return_value="A" * 100) as mock_digital, \
         patch("services.purchase_ocr._extract_ocr_text") as mock_ocr:
        
        text = parse_pdf_text(b"mock pdf bytes")
        assert len(text) == 100
        mock_digital.assert_called_once()
        mock_ocr.assert_not_called()

def test_parse_pdf_text_falls_back_to_ocr_when_scarce():
    # If character count is below threshold, run OCR fallback
    with patch("services.purchase_ocr._extract_digital_text", return_value="Short") as mock_digital, \
         patch("services.purchase_ocr._extract_ocr_text", return_value="Full OCR Text Content Here" * 5) as mock_ocr:
        
        text = parse_pdf_text(b"mock pdf bytes")
        assert "Full OCR Text Content Here" in text
        mock_digital.assert_called_once()
        mock_ocr.assert_called_once()


# ── Mocking OCR Library Dependencies ──────────────────────────────────────────

def test_extract_ocr_text_success():
    mock_img = MagicMock()
    
    # Configure mock modules
    mock_pdf2image.convert_from_bytes.return_value = [mock_img]
    # Length of return string must be >= 50
    mock_pytesseract.image_to_string.return_value = "Extracted OCR Text Content " * 5
    mock_pytesseract.get_languages.return_value = ["eng"]
    
    text = _extract_ocr_text(b"mock pdf bytes")
    assert "Extracted OCR Text Content" in text
    mock_pdf2image.convert_from_bytes.assert_called_once_with(b"mock pdf bytes", dpi=300)
    mock_pytesseract.image_to_string.assert_called_once_with(mock_img, lang="eng")

def test_extract_ocr_text_scanned_threshold_failure():
    mock_img = MagicMock()
    
    mock_pdf2image.convert_from_bytes.return_value = [mock_img]
    mock_pytesseract.image_to_string.return_value = "Too short"
    mock_pytesseract.get_languages.return_value = ["eng"]
    
    # Less than threshold (50 chars) should raise ValueError
    with pytest.raises(ValueError, match="OCR could not extract readable text"):
        _extract_ocr_text(b"mock pdf bytes")

def test_extract_image_text_success():
    mock_pytesseract.image_to_string.return_value = "Image OCR Text"
    mock_pytesseract.get_languages.return_value = ["eng"]
    
    with patch("PIL.Image.open") as mock_image_open:
        text = _extract_image_text(b"mock image bytes")
        assert text == "Image OCR Text"
        mock_image_open.assert_called_once()


# ── Structured Extraction & Fallback Chain ────────────────────────────────────

@patch.dict(os.environ, {"GROQ_API_KEY": "mock_key"})
def test_extract_structured_purchase_invoice_groq_success():
    mock_message = MagicMock()
    mock_message.content = '{"supplier_name": "Groq Supplier", "invoice_number": "G-100", "items": []}'
    
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    
    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]
    
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_completion
    
    # Groq clients are now built through the shared timeout-guarded factory
    # (services/groq_client.make_groq_client, REVIEW_1 GAP-3) — patch that.
    with patch("services.groq_client.make_groq_client", return_value=mock_client) as mock_factory:
        res = extract_structured_purchase_invoice("Raw Text")
        assert res["supplier_name"] == "Groq Supplier"
        assert res["invoice_number"] == "G-100"
        mock_factory.assert_called_once_with("mock_key")

@patch.dict(os.environ, {"GROQ_API_KEY": "mock_key", "CLAUDE_API_KEY": "claude_key"})
def test_extract_structured_purchase_invoice_groq_fail_claude_success():
    # Groq fails, falls back to Claude
    mock_groq_client = MagicMock()
    mock_groq_client.chat.completions.create.side_effect = Exception("Groq API rate limit")
    
    mock_claude_msg = MagicMock()
    mock_content = MagicMock()
    mock_content.text = '{"supplier_name": "Claude Supplier", "invoice_number": "C-200", "items": []}'
    mock_claude_msg.content = [mock_content]
    
    mock_claude_client = MagicMock()
    mock_claude_client.messages.create.return_value = mock_claude_msg
    
    with patch("services.groq_client.make_groq_client", return_value=mock_groq_client), \
         patch("services.purchase_ocr.anthropic.Anthropic", return_value=mock_claude_client) as mock_claude_cls:
        
        res = extract_structured_purchase_invoice("Raw Text")
        assert res["supplier_name"] == "Claude Supplier"
        assert res["invoice_number"] == "C-200"
        mock_claude_cls.assert_called_once_with(api_key="claude_key")

@patch.dict(os.environ, {}, clear=True)
def test_extract_structured_purchase_invoice_no_keys_raises():
    with pytest.raises(ValueError, match="No configured LLM API keys"):
        extract_structured_purchase_invoice("Raw Text")


# ── File type validation ──────────────────────────────────────────────────────

def test_parse_purchase_file_unsupported_ext():
    with pytest.raises(ValueError, match="Unsupported file type"):
        parse_purchase_file(b"text file content", "invoice.txt")

@patch("services.purchase_ocr.parse_pdf_text", return_value="PDF Raw Text")
@patch("services.purchase_ocr.extract_structured_purchase_invoice")
def test_parse_purchase_file_pdf(mock_extract, mock_pdf_text):
    mock_extract.return_value = {"supplier_name": "Test"}
    res = parse_purchase_file(b"pdf bytes", "invoice.pdf")
    assert res == {"supplier_name": "Test"}
    mock_pdf_text.assert_called_once_with(b"pdf bytes")
    mock_extract.assert_called_once_with("PDF Raw Text")

@patch("services.purchase_ocr._extract_image_text", return_value="Image Raw Text")
@patch("services.purchase_ocr.extract_structured_purchase_invoice")
def test_parse_purchase_file_image(mock_extract, mock_img_text):
    mock_extract.return_value = {"supplier_name": "Test Image"}
    res = parse_purchase_file(b"image bytes", "invoice.png")
    assert res == {"supplier_name": "Test Image"}
    mock_img_text.assert_called_once_with(b"image bytes")
    mock_extract.assert_called_once_with("Image Raw Text")


# ── JSON Loose Parsing & Self-Healing Repair ──────────────────────────────────

def test_parse_json_loose_with_repair():
    from services.purchase_ocr import _parse_json_loose
    from unittest.mock import patch

    # 1. Test case where JSON is already valid
    valid_json = '{"supplier_name": "Test Valid"}'
    assert _parse_json_loose(valid_json) == {"supplier_name": "Test Valid"}

    # 2. Test case where JSON is invalid but repaired successfully
    broken_json = '{"supplier_name": "Test Broken" '
    repaired_json = '{"supplier_name": "Test Broken"}'

    with patch("services.purchase_ocr._repair_json_with_llm", return_value=repaired_json) as mock_repair:
        res = _parse_json_loose(broken_json)
        assert res == {"supplier_name": "Test Broken"}
        mock_repair.assert_called_once_with(broken_json.strip())

    # 3. Test case where repair fails and raises JSONDecodeError
    with patch("services.purchase_ocr._repair_json_with_llm", return_value="") as mock_repair:
        import pytest
        import json
        with pytest.raises(json.JSONDecodeError):
            _parse_json_loose(broken_json)


@patch("services.purchase_ocr.os.getenv")
def test_repair_json_with_llm_success(mock_getenv):
    from services.purchase_ocr import _repair_json_with_llm
    from unittest.mock import MagicMock, patch

    mock_getenv.side_effect = lambda k, d=None: "mock_key" if k == "GROQ_API_KEY" else d

    mock_client = MagicMock()
    mock_completion = MagicMock()
    mock_completion.choices = [MagicMock()]
    mock_completion.choices[0].message.content = '{"supplier_name": "Repaired"}'
    mock_client.chat.completions.create.return_value = mock_completion

    with patch("services.groq_client.make_groq_client", return_value=mock_client):
        res = _repair_json_with_llm('{"supplier_name": "Repaired"')
        assert res == '{"supplier_name": "Repaired"}'

