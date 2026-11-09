"""services/brevo_service.py
========================
Brevo (formerly Sendinblue) v3 API client for STATER Bill.
Handles:
  1. Transactional emails (Password reset OTP, Account Verification, Invoice receipts)
  2. Promotional / Contact sync (Automated merchant sync to Brevo Marketing lists)

Zero external SDK dependencies: uses httpx to call Brevo v3 REST endpoints directly.
Includes graceful dev/test fallbacks when BREVO_API_KEY is not configured.
"""
from __future__ import annotations

import logging
import os
from typing import Optional
import httpx

logger = logging.getLogger("bizassist.brevo")

BREVO_API_URL = "https://api.brevo.com/v3"
BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "").strip()
BREVO_SENDER_EMAIL = os.environ.get("BREVO_SENDER_EMAIL", "noreply@staterbill.com").strip()
BREVO_SENDER_NAME = os.environ.get("BREVO_SENDER_NAME", "STATER Bill").strip()


def is_brevo_configured() -> bool:
    """Returns True if a live Brevo API key is mounted."""
    return bool(BREVO_API_KEY and len(BREVO_API_KEY) > 10)


def send_otp_email(to_email: str, recipient_name: str, otp_code: str, username: str) -> bool:
    """Dispatches a secure 6-digit password reset / verification OTP via Brevo."""
    if not to_email or "@" not in to_email:
        logger.warning("[BREVO] Refusing to send OTP: invalid email '%s'", to_email)
        return False

    display_name = (recipient_name or username or "Merchant").strip()
    subject = f"{otp_code} is your STATER Bill verification code"

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0f1117; color: #e5e7eb; margin: 0; padding: 24px; }}
    .container {{ max-width: 520px; margin: 0 auto; background-color: #1a1d24; border: 1px solid #2d3343; border-radius: 14px; padding: 32px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
    .header {{ text-align: center; margin-bottom: 24px; }}
    .brand {{ font-size: 20px; font-weight: 800; color: #f59e0b; letter-spacing: 0.05em; }}
    .subtitle {{ font-size: 11px; color: #9ca3af; text-transform: uppercase; letter-spacing: 0.15em; margin-top: 4px; }}
    .content {{ font-size: 14px; line-height: 1.6; color: #d1d5db; }}
    .otp-box {{ background: linear-gradient(135deg, rgba(245,158,11,0.15) 0%, rgba(217,119,6,0.05) 100%); border: 1.5px dashed #f59e0b; border-radius: 10px; text-align: center; padding: 18px; margin: 24px 0; }}
    .otp-code {{ font-size: 32px; font-weight: 900; letter-spacing: 8px; color: #fbbf24; font-family: monospace; }}
    .meta-box {{ background-color: #12141a; border-radius: 8px; padding: 12px 16px; margin-top: 20px; font-size: 12px; color: #9ca3af; }}
    .footer {{ margin-top: 28px; text-align: center; font-size: 11px; color: #6b7280; border-top: 1px solid #262b36; padding-top: 18px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="brand">STATER Bill</div>
      <div class="subtitle">Smart Counter Billing & POS</div>
    </div>
    <div class="content">
      <p>Hello <strong>{display_name}</strong>,</p>
      <p>We received a request to verify your account or reset the password for your store login.</p>
      <div class="otp-box">
        <div style="font-size: 11px; text-transform: uppercase; color: #f59e0b; font-weight: 700; margin-bottom: 6px;">Your 6-Digit Verification Code</div>
        <div class="otp-code">{otp_code}</div>
      </div>
      <p>This code will expire in <strong>10 minutes</strong>. If you did not request this verification, you can safely ignore this email; your account remains secure.</p>
      <div class="meta-box">
        <div><strong>Store Login Username:</strong> <span style="color: #fbbf24;">{username}</span></div>
      </div>
    </div>
    <div class="footer">
      © {2026} STATER Bill • ARES Pvt Ltd<br>
      High-performance counter billing for modern retail.
    </div>
  </div>
</body>
</html>"""

    if not is_brevo_configured():
        logger.info(
            "[BREVO_DEV_MODE] BREVO_API_KEY is not set. OTP email suppressed for %s. Code: %s, Username: %s",
            to_email, otp_code, username
        )
        return True

    payload = {
        "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
        "to": [{"email": to_email, "name": display_name}],
        "subject": subject,
        "htmlContent": html_content,
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{BREVO_API_URL}/smtp/email",
                headers={
                    "api-key": BREVO_API_KEY,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=payload,
            )
            if resp.status_code in (200, 201, 202):
                logger.info("[BREVO] OTP email delivered to %s (messageId: %s)", to_email, resp.json().get("messageId"))
                return True
            else:
                logger.error("[BREVO] Failed to deliver OTP email to %s: HTTP %s: %s", to_email, resp.status_code, resp.text)
                return False
    except Exception as exc:
        logger.error("[BREVO] Network exception dispatching OTP to %s: %s", to_email, exc)
        return False


def send_welcome_email(to_email: str, recipient_name: str, username: str, business_name: str) -> bool:
    """Dispatches onboarding instructions and welcome details upon registration."""
    if not to_email or "@" not in to_email:
        return False

    display_name = (recipient_name or username or "Merchant").strip()
    subject = f"Welcome to STATER Bill, {business_name}!"

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0f1117; color: #e5e7eb; margin: 0; padding: 24px; }}
    .container {{ max-width: 520px; margin: 0 auto; background-color: #1a1d24; border: 1px solid #2d3343; border-radius: 14px; padding: 32px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
    .brand {{ font-size: 20px; font-weight: 800; color: #f59e0b; }}
    .btn {{ display: inline-block; background: #f59e0b; color: #000; font-weight: 700; text-decoration: none; padding: 12px 24px; border-radius: 8px; margin-top: 16px; }}
    .card {{ background: #12141a; border-radius: 8px; padding: 14px; margin: 16px 0; font-size: 13px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="brand">STATER Bill</div>
    <h2>Welcome to modern counter billing, {display_name}!</h2>
    <p>Your store <strong>{business_name}</strong> is now live with a 14-day Pro trial.</p>
    <div class="card">
      <div><strong>Your Store Username:</strong> <span style="color:#fbbf24;">{username}</span></div>
      <div style="margin-top:6px;"><strong>Web App Login:</strong> <a href="https://app.staterbill.com/login" style="color:#60a5fa;">https://app.staterbill.com</a></div>
    </div>
    <a href="https://app.staterbill.com/login" class="btn">Open Your POS Counter ➔</a>
  </div>
</body>
</html>"""

    if not is_brevo_configured():
        logger.info("[BREVO_DEV_MODE] Welcome email suppressed for %s (%s)", to_email, business_name)
        return True

    payload = {
        "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
        "to": [{"email": to_email, "name": display_name}],
        "subject": subject,
        "htmlContent": html_content,
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{BREVO_API_URL}/smtp/email",
                headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json"},
                json=payload,
            )
            return resp.status_code in (200, 201, 202)
    except Exception as exc:
        logger.warning("[BREVO] Welcome email exception for %s: %s", to_email, exc)
        return False


def sync_contact_to_brevo(email: str, business_name: str, phone: str = "", plan: str = "Trial") -> bool:
    """Syncs a merchant contact into Brevo Contact Lists for promotional/transactional communications."""
    if not is_brevo_configured() or not email or "@" not in email:
        return True

    payload = {
        "email": email.strip().lower(),
        "attributes": {
            "BUSINESS_NAME": business_name,
            "PHONE": phone,
            "PLAN": plan,
        },
        "updateEnabled": True,
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{BREVO_API_URL}/contacts",
                headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json"},
                json=payload,
            )
            return resp.status_code in (200, 201, 204)
    except Exception as exc:
        logger.warning("[BREVO] Failed to sync contact %s to Brevo: %s", email, exc)
        return False
