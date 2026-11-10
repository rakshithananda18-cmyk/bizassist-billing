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
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>STATER Bill Verification Code</title>
</head>
<body style="margin: 0; padding: 28px 12px; background-color: #0b0d12; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #e5e7eb;">
  <div style="max-width: 520px; margin: 0 auto; background-color: #13161f; border: 1px solid #232836; border-radius: 16px; overflow: hidden; box-shadow: 0 12px 40px rgba(0,0,0,0.55);">
    <div style="text-align: center; padding: 32px 24px 22px; border-bottom: 1px solid #1f2430; background-color: #171a25;">
      <div style="font-size: 24px; font-weight: 800; color: #ffffff; letter-spacing: -0.02em; text-transform: uppercase;">
        STATER <span style="color: #c15f3c; font-weight: 700; text-transform: none;">Bill</span>
      </div>
      <div style="font-size: 10px; color: #9ca3af; text-transform: uppercase; letter-spacing: 0.16em; margin-top: 5px; font-weight: 600;">
        στατήρ <span style="color: #c15f3c; font-weight: 800;">•</span> BY ARES &bull; SMART COUNTER BILLING &amp; POS
      </div>
    </div>
    <div style="padding: 32px 28px;">
      <p style="font-size: 14px; line-height: 1.6; color: #d1d5db; margin: 0 0 14px;">
        Hello <strong>{escape(display_name)}</strong>,
      </p>
      <p style="font-size: 14px; line-height: 1.6; color: #9ca3af; margin: 0 0 20px;">
        We received a request to verify your account or reset the password for your store login.
      </p>
      <div style="background: linear-gradient(135deg, rgba(193, 95, 60, 0.16) 0%, rgba(185, 88, 56, 0.05) 100%); border: 1.5px dashed #c15f3c; border-radius: 12px; text-align: center; padding: 20px; margin: 22px 0;">
        <div style="font-size: 11px; text-transform: uppercase; color: #c15f3c; font-weight: 700; letter-spacing: 0.08em; margin-bottom: 8px;">
          Your 6-Digit Verification Code
        </div>
        <div style="font-size: 34px; font-weight: 900; letter-spacing: 8px; color: #ffffff; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;">
          {otp_code}
        </div>
      </div>
      <p style="font-size: 13px; line-height: 1.6; color: #9ca3af; margin: 0 0 18px;">
        This code will expire in <strong style="color: #ffffff;">10 minutes</strong>. If you did not request this verification, you can safely ignore this email; your account remains secure.
      </p>
      <div style="background-color: #181c26; border: 1px solid #262c3b; border-radius: 8px; padding: 12px 16px; font-size: 12px; color: #9ca3af;">
        <strong>Store Login Username:</strong> <span style="color: #ffffff; font-weight: 700; font-family: monospace;">{escape(username)}</span>
      </div>
    </div>
    <div style="padding: 20px 28px 24px; border-top: 1px solid #1f2430; background-color: #10121a; text-align: center; font-size: 11px; color: #6b7280; line-height: 1.6;">
      &copy; 2026 STATER Bill &bull; ARES Enterprise Solutions Pvt Ltd<br>
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
    clean_business = (business_name or display_name or "Your Store").strip()
    subject = f"Welcome to STATER Bill, {clean_business}!"

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Welcome to STATER Bill</title>
</head>
<body style="margin: 0; padding: 28px 12px; background-color: #0b0d12; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #e5e7eb;">
  <div style="max-width: 560px; margin: 0 auto; background-color: #13161f; border: 1px solid #232836; border-radius: 16px; overflow: hidden; box-shadow: 0 12px 40px rgba(0,0,0,0.55);">
    
    <!-- Brand Header -->
    <div style="text-align: center; padding: 32px 24px 22px; border-bottom: 1px solid #1f2430; background-color: #171a25;">
      <div style="font-size: 24px; font-weight: 800; color: #ffffff; letter-spacing: -0.02em; text-transform: uppercase;">
        STATER <span style="color: #c15f3c; font-weight: 700; text-transform: none;">Bill</span>
      </div>
      <div style="font-size: 10px; color: #9ca3af; text-transform: uppercase; letter-spacing: 0.16em; margin-top: 5px; font-weight: 600;">
        στατήρ <span style="color: #c15f3c; font-weight: 800;">•</span> BY ARES &bull; HIGH-PERFORMANCE COUNTER BILLING
      </div>
    </div>

    <!-- Main Content -->
    <div style="padding: 32px 28px;">
      
      <div style="text-align: center; margin-bottom: 24px;">
        <span style="display: inline-block; background-color: rgba(193, 95, 60, 0.14); border: 1px solid rgba(193, 95, 60, 0.35); border-radius: 20px; padding: 4px 14px; font-size: 11px; font-weight: 700; color: #e39a77; letter-spacing: 0.08em; text-transform: uppercase;">
          14-Day Free Pro Trial Active
        </span>
        <h1 style="font-size: 22px; font-weight: 700; color: #ffffff; letter-spacing: -0.03em; line-height: 1.3; margin: 14px 0 8px;">
          Welcome to modern counter billing, {escape(display_name)}!
        </h1>
        <p style="font-size: 14px; line-height: 1.6; color: #9ca3af; margin: 0;">
          Your store <strong style="color: #ffffff;">{escape(clean_business)}</strong> is now ready. Start barcode billing, manage stock, and test your counter with zero friction.
        </p>
      </div>

      <!-- Account Credentials Card -->
      <div style="background-color: #181c26; border: 1px solid #262c3b; border-radius: 12px; padding: 18px 20px; margin: 24px 0;">
        <div style="font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em; color: #c15f3c; margin-bottom: 12px;">
          Store Credentials &amp; Access
        </div>
        <table style="width: 100%; border-collapse: collapse;">
          <tr>
            <td style="padding: 7px 0; font-size: 13px; color: #9ca3af;">Store Name</td>
            <td style="padding: 7px 0; font-size: 13px; font-weight: 600; color: #ffffff; text-align: right;">{escape(clean_business)}</td>
          </tr>
          <tr>
            <td style="padding: 7px 0; font-size: 13px; color: #9ca3af; border-top: 1px solid #1f2533;">Username / Identifier</td>
            <td style="padding: 7px 0; font-size: 13px; text-align: right; border-top: 1px solid #1f2533;">
              <span style="font-family: monospace; background-color: #0f1118; color: #ffffff; padding: 2px 7px; border-radius: 5px; border: 1px solid #282e3d; font-weight: 700;">{escape(username)}</span>
            </td>
          </tr>
          <tr>
            <td style="padding: 7px 0; font-size: 13px; color: #9ca3af; border-top: 1px solid #1f2533;">Web Application</td>
            <td style="padding: 7px 0; font-size: 13px; font-weight: 600; text-align: right; border-top: 1px solid #1f2533;">
              <a href="https://app.staterbill.com/login" style="color: #c15f3c; text-decoration: none;">app.staterbill.com/login</a>
            </td>
          </tr>
        </table>
      </div>

      <!-- Feature Checklist -->
      <div style="margin: 24px 0 28px;">
        <div style="font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #d1d5db; margin-bottom: 12px;">
          What you can do right now:
        </div>
        <table style="width: 100%; border-collapse: collapse;">
          <tr>
            <td style="width: 22px; vertical-align: top; padding: 4px 0; color: #64856c; font-weight: 800; font-size: 14px;">✓</td>
            <td style="padding: 4px 0 8px 6px; font-size: 13px; color: #d1d5db; line-height: 1.5;">
              <strong style="color: #ffffff;">Fast Barcode Billing:</strong> Scan barcodes, manage open tabs, and print thermal receipts.
            </td>
          </tr>
          <tr>
            <td style="width: 22px; vertical-align: top; padding: 4px 0; color: #64856c; font-weight: 800; font-size: 14px;">✓</td>
            <td style="padding: 4px 0 8px 6px; font-size: 13px; color: #d1d5db; line-height: 1.5;">
              <strong style="color: #ffffff;">Multi-Tier Pricing:</strong> Retail, wholesale, and distributor prices on a single product.
            </td>
          </tr>
          <tr>
            <td style="width: 22px; vertical-align: top; padding: 4px 0; color: #64856c; font-weight: 800; font-size: 14px;">✓</td>
            <td style="padding: 4px 0 8px 6px; font-size: 13px; color: #d1d5db; line-height: 1.5;">
              <strong style="color: #ffffff;">Desktop Offline Mode:</strong> Download our desktop app to bill uninterrupted without internet.
            </td>
          </tr>
        </table>
      </div>

      <!-- CTA Button -->
      <div style="text-align: center; margin: 28px 0 16px;">
        <a href="https://app.staterbill.com/login" style="display: inline-block; background-color: #b95838; color: #ffffff !important; font-weight: 700; font-size: 14px; text-decoration: none; padding: 13px 32px; border-radius: 10px; box-shadow: 0 4px 16px rgba(185, 88, 56, 0.35); letter-spacing: 0.01em;">
          Open Your Billing Counter ➔
        </a>
      </div>
      <p style="font-size: 12px; color: #9ca3af; text-align: center; line-height: 1.5; margin: 0;">
        No credit card required &bull; Full Pro features unlocked for 14 days
      </p>

    </div>

    <!-- Footer -->
    <div style="padding: 22px 28px 28px; border-top: 1px solid #1f2430; background-color: #10121a; text-align: center; font-size: 11px; color: #6b7280; line-height: 1.6;">
      <p style="margin: 0 0 6px;">
        Need help setting up your catalogue or hardware? Reach our team at <a href="mailto:support@staterbill.com" style="color: #c15f3c; text-decoration: none;">support@staterbill.com</a>
      </p>
      <p style="margin: 0;">
        &copy; 2026 STATER Bill &bull; ARES Enterprise Solutions Pvt Ltd &bull; All rights reserved.
      </p>
    </div>

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
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Account Details Updated</title>
</head>
<body style="margin: 0; padding: 28px 12px; background-color: #0b0d12; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #e5e7eb;">
  <div style="max-width: 520px; margin: 0 auto; background-color: #13161f; border: 1px solid #232836; border-radius: 16px; overflow: hidden; box-shadow: 0 12px 40px rgba(0,0,0,0.55);">
    <div style="text-align: center; padding: 32px 24px 22px; border-bottom: 1px solid #1f2430; background-color: #171a25;">
      <div style="font-size: 24px; font-weight: 800; color: #ffffff; letter-spacing: -0.02em; text-transform: uppercase;">
        STATER <span style="color: #c15f3c; font-weight: 700; text-transform: none;">Bill</span>
      </div>
      <div style="font-size: 10px; color: #9ca3af; text-transform: uppercase; letter-spacing: 0.16em; margin-top: 5px; font-weight: 600;">
        στατήρ <span style="color: #c15f3c; font-weight: 800;">•</span> BY ARES &bull; SECURITY NOTIFICATION
      </div>
    </div>
    <div style="padding: 32px 28px;">
      <h2 style="font-size: 20px; font-weight: 700; color: #ffffff; margin: 0 0 12px;">Account Details Updated</h2>
      <p style="font-size: 14px; line-height: 1.6; color: #d1d5db; margin: 0 0 14px;">Hello <strong>{escape(display_name)}</strong>,</p>
      <p style="font-size: 14px; line-height: 1.6; color: #9ca3af; margin: 0 0 16px;">This is a confirmation that changes were recently made to your business account:</p>
      <div style="background-color: #181c26; border: 1px solid #262c3b; border-radius: 10px; padding: 14px 18px; margin: 16px 0;">
        <ul style="padding-left: 20px; margin: 0; color: #e39a77; font-size: 13px; line-height: 1.6;">
          {changes_html}
        </ul>
      </div>
      <div style="background-color: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 8px; padding: 14px; color: #f87171; font-size: 12px; margin-top: 18px; line-height: 1.5;">
        <strong>Didn't make this change?</strong> If you did not authorize these account modifications, please contact support at <a href="mailto:support@staterbill.com" style="color: #fca5a5; text-decoration: underline;">support@staterbill.com</a> immediately.
      </div>
    </div>
    <div style="padding: 20px 28px 24px; border-top: 1px solid #1f2430; background-color: #10121a; text-align: center; font-size: 11px; color: #6b7280; line-height: 1.6;">
      &copy; 2026 STATER Bill Security &bull; High-performance counter billing for modern retail.
    </div>
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
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Password Change Notice</title>
</head>
<body style="margin: 0; padding: 28px 12px; background-color: #0b0d12; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #e5e7eb;">
  <div style="max-width: 520px; margin: 0 auto; background-color: #13161f; border: 1px solid #232836; border-radius: 16px; overflow: hidden; box-shadow: 0 12px 40px rgba(0,0,0,0.55);">
    <div style="text-align: center; padding: 32px 24px 22px; border-bottom: 1px solid #1f2430; background-color: #171a25;">
      <div style="font-size: 24px; font-weight: 800; color: #ffffff; letter-spacing: -0.02em; text-transform: uppercase;">
        STATER <span style="color: #c15f3c; font-weight: 700; text-transform: none;">Bill</span>
      </div>
      <div style="font-size: 10px; color: #9ca3af; text-transform: uppercase; letter-spacing: 0.16em; margin-top: 5px; font-weight: 600;">
        στατήρ <span style="color: #c15f3c; font-weight: 800;">•</span> BY ARES &bull; SECURITY NOTIFICATION
      </div>
    </div>
    <div style="padding: 32px 28px;">
      <h2 style="font-size: 20px; font-weight: 700; color: #ffffff; margin: 0 0 12px;">Password Change Notice</h2>
      <p style="font-size: 14px; line-height: 1.6; color: #d1d5db; margin: 0 0 14px;">Hello <strong>{escape(display_name)}</strong>,</p>
      <p style="font-size: 14px; line-height: 1.6; color: #9ca3af; margin: 0 0 16px;">The password for your store login (<strong>{escape(username)}</strong>) was just changed successfully.</p>
      <div style="background-color: #181c26; border: 1px solid #262c3b; border-radius: 8px; padding: 14px 18px; margin: 16px 0; font-size: 13px;">
        <div><strong>Affected Account:</strong> <span style="color:#ffffff; font-weight: 700; font-family: monospace;">{escape(username)}</span></div>
        <div style="margin-top:6px; color:#9ca3af;"><strong>Time:</strong> Just now</div>
      </div>
      <div style="background-color: rgba(239, 68, 68, 0.12); border: 1.5px solid #ef4444; border-radius: 8px; padding: 14px; color: #fca5a5; font-size: 13px; margin-top: 18px; line-height: 1.5;">
        <strong>Didn't make this change?</strong><br>
        If you did not authorize this change, please reset your password immediately at <a href="https://app.staterbill.com/login" style="color:#ffffff; font-weight: 700; text-decoration: underline;">https://app.staterbill.com/login</a> or reach our emergency support team at <a href="mailto:support@staterbill.com" style="color:#ffffff; font-weight: 700;">support@staterbill.com</a>.
      </div>
    </div>
    <div style="padding: 20px 28px 24px; border-top: 1px solid #1f2430; background-color: #10121a; text-align: center; font-size: 11px; color: #6b7280; line-height: 1.6;">
      &copy; 2026 STATER Bill Security &bull; High-performance counter billing for modern retail.
    </div>
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
