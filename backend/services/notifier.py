"""
notifier.py
===========
Sends email notifications for BizAssist alerts via SMTP (free).

Configure in .env:
  EMAIL_HOST  — default: smtp.gmail.com
  EMAIL_PORT  — default: 587
  EMAIL_USER  — your Gmail address
  EMAIL_PASS  — Gmail App Password (not your main password)
  EMAIL_FROM  — optional display address, defaults to EMAIL_USER

WhatsApp support can be added later via Twilio when needed.
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

logger = logging.getLogger("bizassist.notifier")

EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USER = os.getenv("EMAIL_USER", "")
EMAIL_PASS = os.getenv("EMAIL_PASS", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "") or EMAIL_USER


def send_email(to: str, subject: str, body: str) -> bool:
    if not EMAIL_USER or not EMAIL_PASS:
        logger.warning("[Email] EMAIL_USER / EMAIL_PASS not set in .env — skipping.")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = EMAIL_FROM
        msg["To"]      = to
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_FROM, to, msg.as_string())

        logger.info(f"[Email] Sent to {to}: {subject}")
        return True
    except Exception as e:
        logger.error(f"[Email] Failed to send to {to}: {e}")
        return False


def notify(email: Optional[str], whatsapp: Optional[str], subject: str, body: str):
    """
    Send notification. whatsapp param is accepted but ignored for now.
    Add Twilio here later when needed.
    """
    if email:
        send_email(email, subject, body)
    else:
        logger.warning(f"[Notify] No email configured — alert not delivered: '{subject}'")
