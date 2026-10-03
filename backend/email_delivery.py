import asyncio
import os
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from sqlalchemy import or_, select

from database import Notification, SessionLocal
from settings import email_configured, flag


def send_email(title: str, body: str):
    message = EmailMessage()
    message["Subject"] = f"Hot Monitor：{title[:150].replace(chr(10), ' ').replace(chr(13), ' ')}"
    message["From"] = os.environ["SMTP_FROM"]
    message["To"] = os.environ["SMTP_TO"]
    message.set_content(body)
    ssl_enabled = flag("SMTP_SSL")
    smtp_class = smtplib.SMTP_SSL if ssl_enabled else smtplib.SMTP
    kwargs = {"context": ssl.create_default_context()} if ssl_enabled else {}
    with smtp_class(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "465" if ssl_enabled else "587")), timeout=15, **kwargs) as smtp:
        if not ssl_enabled and flag("SMTP_STARTTLS", True):
            smtp.starttls(context=ssl.create_default_context())
        if os.getenv("SMTP_USERNAME"):
            smtp.login(os.environ["SMTP_USERNAME"], os.environ.get("SMTP_PASSWORD", ""))
        smtp.send_message(message)


class EmailDelivery:
    def __init__(self, sessions=SessionLocal):
        self.sessions = sessions
        self.lock = asyncio.Lock()

    async def deliver(self):
        if not email_configured() or self.lock.locked():
            return
        async with self.lock:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            with self.sessions() as session:
                ids = list(session.scalars(select(Notification.id).where(
                    Notification.email_status.in_(["pending", "sending"]),
                    or_(Notification.email_next_at.is_(None), Notification.email_next_at <= now),
                ).order_by(Notification.id).limit(20)))
            for notification_id in ids:
                with self.sessions() as session:
                    item = session.get(Notification, notification_id)
                    if item is None:
                        continue
                    if item.email_attempts >= 3:
                        item.email_status = "failed"
                        session.commit()
                        continue
                    item.email_status = "sending"
                    item.email_attempts += 1
                    item.email_next_at = now + timedelta(minutes=10)
                    title, body = item.title, item.body
                    session.commit()
                try:
                    await asyncio.to_thread(send_email, title, body)
                    status = "sent"
                except Exception:
                    status = "pending"
                with self.sessions() as session:
                    item = session.get(Notification, notification_id)
                    if item is None:
                        continue
                    item.email_status = "failed" if status == "pending" and item.email_attempts >= 3 else status
                    item.email_next_at = now + timedelta(seconds=60 * 2 ** item.email_attempts) if status == "pending" else None
                    session.commit()
