from __future__ import annotations

import re
import smtplib
import ssl
from email.utils import formataddr
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
        if not to_email or "@" not in to_email:
            raise ValueError("Recipient email is missing or invalid.")

        from_email = self._settings.smtp_from_email or self._settings.smtp_username
        from_name = self._settings.smtp_from_name
        formatted_from = formataddr((from_name, from_email)) if from_name else from_email

        message = EmailMessage()
        message["From"] = formatted_from
        message["To"] = to_email
        message["Subject"] = subject
        if self._looks_like_html(body):
            message.set_content(self._html_to_text(body))
            message.add_alternative(body, subtype="html")
        else:
            message.set_content(body)
        context = ssl.create_default_context()

        if self._settings.smtp_use_ssl:
            with smtplib.SMTP_SSL(self._settings.smtp_host, self._settings.smtp_port, timeout=30, context=context) as server:
                server.login(self._settings.smtp_username, self._settings.smtp_password)
                server.send_message(message)
            return

        with smtplib.SMTP(self._settings.smtp_host, self._settings.smtp_port, timeout=30) as server:
            server.ehlo()
            if self._settings.smtp_use_tls:
                server.starttls(context=context)
                server.ehlo()
            server.login(self._settings.smtp_username, self._settings.smtp_password)
            server.send_message(message)

    @staticmethod
    def _looks_like_html(body: str) -> bool:
        lowered = body.lower()
        return "<html" in lowered or "<body" in lowered or "<div" in lowered or "<p" in lowered

    @staticmethod
    def _html_to_text(body: str) -> str:
        text = re.sub(r"(?i)<br\s*/?>", "\n", body)
        text = re.sub(r"(?i)</p>", "\n\n", text)
        text = re.sub(r"(?i)</li>", "\n", text)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
