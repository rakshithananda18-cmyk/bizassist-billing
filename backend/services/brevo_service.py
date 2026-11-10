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
from html import escape
import os
from typing import Optional
from sqlalchemy import func
import httpx

logger = logging.getLogger("bizassist.brevo")

BREVO_API_URL = "https://api.brevo.com/v3"
BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "").strip()
BREVO_SENDER_EMAIL = os.environ.get("BREVO_SENDER_EMAIL", "support@staterbill.com").strip()
BREVO_SENDER_NAME = os.environ.get("BREVO_SENDER_NAME", "STATER Bill").strip()


def log_email_dispatch(to_email: str, subject: str, template_type: str, status: str = "sent", details: Optional[str] = None, business_id: Optional[int] = None):
    try:
        from database.db import SessionLocal
        from database.models import EmailLog, User
        with SessionLocal() as db:
            if business_id is not None:
                from database.security import bind_tenant
                bind_tenant(db, business_id)
                u = db.get(User, business_id)
            else:
                from database.security import find_owner_by_identifier
                u = find_owner_by_identifier(db, to_email)
            record = EmailLog(
                business_id=u.id if u else None,
                recipient_email=to_email.strip().lower(),
                subject=subject,
                template_type=template_type,
                status=status,
                provider="brevo",
                details=details,
            )
            db.add(record)
            db.commit()
    except Exception as exc:
        logger.debug("[BREVO] Non-fatal email log error: %s", exc)


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
      <p>Hello <strong>{escape(display_name)}</strong>,</p>
      <p>We received a request to verify your account or reset the password for your store login.</p>
      <div class="otp-box">
        <div style="font-size: 11px; text-transform: uppercase; color: #f59e0b; font-weight: 700; margin-bottom: 6px;">Your 6-Digit Verification Code</div>
        <div class="otp-code">{otp_code}</div>
      </div>
      <p>This code will expire in <strong>10 minutes</strong>. If you did not request this verification, you can safely ignore this email; your account remains secure.</p>
      <div class="meta-box">
        <div><strong>Store Login Username:</strong> <span style="color: #fbbf24;">{escape(username)}</span></div>
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
        log_email_dispatch(to_email, subject, "otp", status="dev_suppressed", details=f"Verification code sent (username: {username})")
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
                log_email_dispatch(to_email, subject, "otp", status="sent", details=f"Delivered (messageId: {resp.json().get('messageId')})")
                return True
            else:
                logger.error("[BREVO] Failed to deliver OTP email to %s: HTTP %s: %s", to_email, resp.status_code, resp.text)
                log_email_dispatch(to_email, subject, "otp", status="failed", details=f"HTTP {resp.status_code}")
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
    <h2>Welcome to modern counter billing, {escape(display_name)}!</h2>
    <p>Your store <strong>{escape(business_name)}</strong> is now live with a 14-day Pro trial.</p>
    <div class="card">
      <div><strong>Your Store Username:</strong> <span style="color:#fbbf24;">{escape(username)}</span></div>
      <div style="margin-top:6px;"><strong>Web App Login:</strong> <a href="https://app.staterbill.com/login" style="color:#60a5fa;">https://app.staterbill.com</a></div>
    </div>
    <a href="https://app.staterbill.com/login" class="btn">Open Your POS Counter ➔</a>
  </div>
</body>
</html>"""

    if not is_brevo_configured():
        logger.info("[BREVO_DEV_MODE] Welcome email suppressed for %s (%s)", to_email, business_name)
        log_email_dispatch(to_email, subject, "welcome", status="dev_suppressed", details=f"Store: {business_name}, User: {username}")
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
            ok = resp.status_code in (200, 201, 202)
            log_email_dispatch(to_email, subject, "welcome", status="sent" if ok else "failed", details=f"Store: {business_name}, User: {username}")
            return ok
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


def send_account_update_email(to_email: str, recipient_name: str, changes_list: list[str], *, business_id: Optional[int] = None) -> bool:
    """Dispatches a security notification email when store account details are updated."""
    if not to_email or "@" not in to_email:
        return False

    display_name = (recipient_name or "Merchant").strip()
    subject = f"Security Alert: Account details updated for {display_name}"
    changes_html = "".join([f"<li style='margin-bottom:6px;'>{escape(str(c))}</li>" for c in changes_list]) if changes_list else "<li>Store account profile details</li>"

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0f1117; color: #e5e7eb; margin: 0; padding: 24px; }}
    .container {{ max-width: 520px; margin: 0 auto; background-color: #1a1d24; border: 1px solid #2d3343; border-radius: 14px; padding: 32px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
    .brand {{ font-size: 20px; font-weight: 800; color: #f59e0b; }}
    .card {{ background: #12141a; border-radius: 8px; padding: 14px; margin: 16px 0; font-size: 13px; }}
    .alert-box {{ background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 8px; padding: 12px; color: #f87171; font-size: 12px; margin-top: 18px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="brand">STATER Bill</div>
    <h2>Account Details Updated</h2>
    <p>Hello <strong>{escape(display_name)}</strong>,</p>
    <p>This is a confirmation that changes were recently made to your business account:</p>
    <div class="card">
      <ul style="padding-left: 20px; margin: 0; color: #fbbf24;">
        {changes_html}
      </ul>
    </div>
    <div class="alert-box">
      <strong>Didn't make this change?</strong> If you did not authorize these account modifications, please contact support at support@staterbill.com immediately.
    </div>
    <p style="font-size: 11px; color: #6b7280; margin-top: 24px; border-top: 1px solid #262b36; padding-top: 12px;">
      STATER Bill Security &bull; High-performance counter billing for modern retail.
    </p>
  </div>
</body>
</html>"""

    if not is_brevo_configured():
        logger.info("[BREVO_DEV_MODE] Account update email suppressed for %s: %s", to_email, changes_list)
        log_email_dispatch(to_email, subject, "account_update", status="dev_suppressed", details=f"Updated: {', '.join(changes_list)}", business_id=business_id)
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
            ok = resp.status_code in (200, 201, 202)
            log_email_dispatch(to_email, subject, "account_update", status="sent" if ok else "failed", details=f"Updated: {', '.join(changes_list)}", business_id=business_id)
            return ok
    except Exception as exc:
        logger.warning("[BREVO] Account update email exception for %s: %s", to_email, exc)
        log_email_dispatch(to_email, subject, "account_update", status="failed", details="Provider request failed", business_id=business_id)
        return False


def send_password_changed_email(to_email: str, recipient_name: str, username: str, *, business_id: Optional[int] = None) -> bool:
    """Dispatches a critical security alert when an account password has been changed."""
    if not to_email or "@" not in to_email:
        return False

    display_name = (recipient_name or username or "Merchant").strip()
    subject = f"Security Alert: Your STATER Bill password has been changed"

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0f1117; color: #e5e7eb; margin: 0; padding: 24px; }}
    .container {{ max-width: 520px; margin: 0 auto; background-color: #1a1d24; border: 1px solid #2d3343; border-radius: 14px; padding: 32px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
    .brand {{ font-size: 20px; font-weight: 800; color: #f59e0b; }}
    .card {{ background: #12141a; border-radius: 8px; padding: 14px; margin: 16px 0; font-size: 13px; }}
    .alert-box {{ background: rgba(239, 68, 68, 0.12); border: 1.5px solid #ef4444; border-radius: 8px; padding: 14px; color: #fca5a5; font-size: 13px; margin-top: 18px; line-height: 1.5; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="brand">STATER Bill</div>
    <h2>Password Change Notice</h2>
    <p>Hello <strong>{escape(display_name)}</strong>,</p>
    <p>The password for your store login (<strong>{escape(username)}</strong>) was just changed successfully.</p>
    <div class="card">
      <div><strong>Affected Account:</strong> <span style="color:#fbbf24;">{escape(username)}</span></div>
      <div style="margin-top:4px;"><strong>Time:</strong> Just now</div>
    </div>
    <div class="alert-box">
      <strong>Didn't make this change?</strong><br>
      If you did not authorize this change, please reset your password immediately at <a href="https://app.staterbill.com/login" style="color:#93c5fd;">https://app.staterbill.com/login</a> or reach our emergency support team at support@staterbill.com.
    </div>
    <p style="font-size: 11px; color: #6b7280; margin-top: 24px; border-top: 1px solid #262b36; padding-top: 12px;">
      STATER Bill Security &bull; High-performance counter billing for modern retail.
    </p>
  </div>
</body>
</html>"""

    if not is_brevo_configured():
        logger.info("[BREVO_DEV_MODE] Password changed email suppressed for %s (User: %s)", to_email, username)
        log_email_dispatch(to_email, subject, "password_changed", status="dev_suppressed", details=f"User: {username}", business_id=business_id)
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
            ok = resp.status_code in (200, 201, 202)
            log_email_dispatch(to_email, subject, "password_changed", status="sent" if ok else "failed", details=f"User: {username}", business_id=business_id)
            return ok
    except Exception as exc:
        logger.warning("[BREVO] Password changed email exception for %s: %s", to_email, exc)
        log_email_dispatch(to_email, subject, "password_changed", status="failed", details="Provider request failed", business_id=business_id)
        return False
