from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app


class EmailDeliveryTests(unittest.TestCase):
    def test_send_email_preserves_personalized_html(self) -> None:
        personalized_html = """
        <html><body>
          <h2>Superplane issues matched to your skills</h2>
          <a href="https://github.com/superplanehq/superplane/issues/123">#123 Improve workflow UI</a>
        </body></html>
        """.strip()
        settings = Settings(
            smtp_host="smtp.example.com",
            smtp_username="sender@example.com",
            smtp_password="app-password",
        )

        with (
            patch("app.main.get_settings", return_value=settings),
            patch("app.main.Mailer.send") as send,
        ):
            response = TestClient(app).post(
                "/send-email",
                json={
                    "email": "developer@example.com",
                    "subject": "Personalized Superplane issues",
                    "body": personalized_html,
                },
            )

        self.assertEqual(response.status_code, 200)
        send.assert_called_once_with(
            to_email="developer@example.com",
            subject="Personalized Superplane issues",
            body=personalized_html,
        )


if __name__ == "__main__":
    unittest.main()
