from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.config import Settings


class Mailer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def send(self, *, to_email: str, subject: str, body: str) -> None:
        if not self._settings.smtp_host:
            raise ValueError("SMTP_HOST is not configured.")
        if not self._settings.smtp_username:
            raise ValueError("SMTP_USERNAME is not configured.")
        if not self._settings.smtp_password:
            raise ValueError("SMTP_PASSWORD is not configured.")

        from_email = self._settings.smtp_from_email or self._settings.smtp_username

        message = EmailMessage()
        message["From"] = from_email
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body)

        with smtplib.SMTP(self._settings.smtp_host, self._settings.smtp_port, timeout=30) as server:
            if self._settings.smtp_use_tls:
                server.starttls()
            server.login(self._settings.smtp_username, self._settings.smtp_password)
            server.send_message(message)
