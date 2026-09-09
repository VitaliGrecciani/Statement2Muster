import os
import json
import logging
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger("statement2muster.email")

class EmailDeliveryService:
    """
    Pluggable Email Delivery Service supporting:
    - memory / test outbox
    - SMTP
    - local outbox file (for test harness verification)
    """
    _test_inbox: List[Dict[str, Any]] = []

    @classmethod
    def get_test_inbox(cls) -> List[Dict[str, Any]]:
        return list(cls._test_inbox)

    @classmethod
    def clear_test_inbox(cls):
        cls._test_inbox.clear()

    @classmethod
    async def send_verification_email(
        cls,
        recipient: str,
        code: str,
        expires_at: datetime.datetime
    ) -> bool:
        """
        Sends verification OTP email to recipient.
        Returns True on successful delivery, returns False on failure (C03).
        """
        from app.core.config import settings

        entry = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "recipient": recipient,
            "subject": "Your Statement2Muster Verification Code",
            "code": code,
            "expires_at": expires_at.isoformat()
        }

        backend = getattr(settings, "EMAIL_BACKEND", "memory").lower()

        # Branch 1: Memory backend (RAM-only; zero disk persistence for Zero Durable Retention)
        if backend == "memory":
            cls._test_inbox.append(entry)
            if len(cls._test_inbox) > 50:
                cls._test_inbox.pop(0)
            logger.info(f"Verification email recorded for {recipient} via backend 'memory'.")
            return True

        # Branch 2: File backend (dev / local test harness only)
        elif backend == "file":
            try:
                outbox_path = getattr(settings, "EMAIL_OUTBOX_PATH", "docs/audit_2026-09-09_round3/email_outbox.jsonl")
                outbox_file = Path(outbox_path)
                if outbox_file.is_dir():
                    logger.error(f"Configured outbox path is a directory, not a file: {outbox_path}")
                    return False
                outbox_file.parent.mkdir(parents=True, exist_ok=True)
                with open(outbox_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
                logger.info(f"Verification email recorded for {recipient} via backend 'file'.")
                return True
            except Exception as e:
                logger.error(f"Failed to write verification email to outbox file: {e}")
                return False

        # Branch 3: SMTP backend (standard library smtplib via thread, zero aiosmtplib dependency)
        elif backend == "smtp":
            smtp_host = getattr(settings, "SMTP_HOST", None)
            if not smtp_host:
                logger.error("SMTP backend selected but SMTP_HOST is not configured.")
                return False

            import asyncio
            import smtplib
            from email.message import EmailMessage

            msg = EmailMessage()
            msg["From"] = getattr(settings, "SMTP_FROM", "no-reply@statement2muster.com")
            msg["To"] = recipient
            msg["Subject"] = entry["subject"]
            msg.set_content(f"Your Statement2Muster login code is: {code}\nThis code expires in 10 minutes.")

            def _send_sync():
                port = getattr(settings, "SMTP_PORT", 587)
                username = getattr(settings, "SMTP_USER", None)
                password = getattr(settings, "SMTP_PASSWORD", None)
                if port == 465:
                    with smtplib.SMTP_SSL(smtp_host, port, timeout=10) as server:
                        if username and password:
                            server.login(username, password)
                        server.send_message(msg)
                else:
                    with smtplib.SMTP(smtp_host, port, timeout=10) as server:
                        server.starttls()
                        if username and password:
                            server.login(username, password)
                        server.send_message(msg)

            try:
                await asyncio.to_thread(_send_sync)
                logger.info(f"Verification email successfully delivered to {recipient} via SMTP.")
                return True
            except Exception as e:
                logger.error(f"Failed to send email via SMTP to {recipient}: {e}")
                return False

        else:
            logger.error(f"Unsupported email backend: {backend}")
            return False

email_service = EmailDeliveryService()
