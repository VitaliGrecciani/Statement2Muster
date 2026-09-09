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
        Returns True on successful delivery, raises or returns False on failure.
        """
        from app.core.config import settings

        entry = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "recipient": recipient,
            "subject": "Your Statement2Muster Verification Code",
            "code": code,
            "expires_at": expires_at.isoformat()
        }

        # 1. Always record in-memory for zero-disk inspection and testing
        cls._test_inbox.append(entry)

        # 2. Write to outbox file if path configured or available
        try:
            outbox_path = getattr(settings, "EMAIL_OUTBOX_PATH", "docs/audit_2026-09-09_round3/email_outbox.jsonl")
            outbox_file = Path(outbox_path)
            outbox_file.parent.mkdir(parents=True, exist_ok=True)
            with open(outbox_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.debug(f"Outbox file write skipped: {e}")

        # 3. Handle live SMTP delivery if configured
        backend = getattr(settings, "EMAIL_BACKEND", "memory").lower()
        if backend == "smtp":
            smtp_host = getattr(settings, "SMTP_HOST", None)
            if not smtp_host:
                logger.error("SMTP backend selected but SMTP_HOST is not configured.")
                return False
            try:
                import aiosmtplib
                from email.message import EmailMessage

                msg = EmailMessage()
                msg["From"] = getattr(settings, "SMTP_FROM", "no-reply@statement2muster.com")
                msg["To"] = recipient
                msg["Subject"] = entry["subject"]
                msg.set_content(f"Your Statement2Muster login code is: {code}\nThis code expires in 10 minutes.")

                await aiosmtplib.send(
                    msg,
                    hostname=smtp_host,
                    port=getattr(settings, "SMTP_PORT", 587),
                    username=getattr(settings, "SMTP_USER", None),
                    password=getattr(settings, "SMTP_PASSWORD", None),
                    start_tls=True
                )
                logger.info(f"Verification email successfully delivered to {recipient} via SMTP.")
                return True
            except Exception as e:
                logger.error(f"Failed to send email via SMTP to {recipient}: {e}")
                return False

        logger.info(f"Verification email recorded for {recipient} via backend '{backend}'.")
        return True

email_service = EmailDeliveryService()
