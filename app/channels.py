from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

import httpx

from app.metrics import ALERTS_SENT

logger = logging.getLogger(__name__)


class WhatsAppClient:
    def __init__(self, webhook_url: str, timeout_sec: float = 5.0, bearer_token: str | None = None):
        self.webhook_url = webhook_url
        self.timeout_sec = timeout_sec
        self.bearer_token = bearer_token

    def send(self, message_text: str, payload: dict) -> tuple[bool, str | None]:
        headers = {"Content-Type": "application/json"}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"

        body = {
            "text": message_text,
            "event": payload,
        }

        try:
            response = httpx.post(
                self.webhook_url,
                json=body,
                headers=headers,
                timeout=self.timeout_sec,
            )
            response.raise_for_status()
            ALERTS_SENT.labels(channel="whatsapp", status="success").inc()
            return True, None
        except Exception as exc:  # noqa: BLE001
            logger.exception("whatsapp_send_failed")
            ALERTS_SENT.labels(channel="whatsapp", status="failed").inc()
            return False, str(exc)


class EmailClient:
    def __init__(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        sender: str,
        starttls: bool = True,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = sender
        self.starttls = starttls

    def send(self, recipients: list[str], subject: str, body: str) -> tuple[bool, str | None]:
        if not recipients:
            return False, "no_email_recipients"

        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = ", ".join(recipients)
        message["Subject"] = subject
        message.set_content(body)

        try:
            with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
                if self.starttls:
                    smtp.starttls()
                if self.username:
                    smtp.login(self.username, self.password or "")
                smtp.send_message(message)
            ALERTS_SENT.labels(channel="email", status="success").inc()
            return True, None
        except Exception as exc:  # noqa: BLE001
            logger.exception("email_send_failed")
            ALERTS_SENT.labels(channel="email", status="failed").inc()
            return False, str(exc)
