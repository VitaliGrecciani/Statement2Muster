"""Issue a single-use accounting firm invitation from the backend host.

Run in the backend container:
python -m app.scripts.issue_kanzlei_invite name@kanzlei.de
Copy the displayed code into the invitation email. It is never stored in clear text.
"""
import argparse
import asyncio
import datetime
import hashlib
import secrets

from app.db.models import KanzleiInvite
from app.db.session import async_session_maker, init_db


async def issue(email: str, validity_days: int) -> None:
    await init_db()
    code = secrets.token_urlsafe(32)
    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=validity_days)
    async with async_session_maker() as db:
        db.add(KanzleiInvite(
            code_hash=hashlib.sha256(code.encode()).hexdigest(),
            email=email.strip().lower(),
            expires_at=expires_at.replace(tzinfo=None),
        ))
        await db.commit()
    print(f"Email: {email.strip().lower()}")
    print(f"Einladungscode: {code}")
    print(f"Einlösung bis: {expires_at.date().isoformat()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Issue a one-use Kanzlei trial invitation")
    parser.add_argument("email", help="Invited business email address")
    parser.add_argument("--validity-days", type=int, default=60)
    arguments = parser.parse_args()
    if arguments.validity_days < 1 or arguments.validity_days > 365:
        parser.error("--validity-days must be between 1 and 365")
    asyncio.run(issue(arguments.email, arguments.validity_days))

