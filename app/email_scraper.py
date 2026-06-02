from __future__ import annotations

import asyncio
import re
import shutil

from app.config import Settings

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


class GitHubEmailScraperClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def find_email(self, username: str) -> str | None:
        command = shutil.which("github-email-scraper")
        if not command:
            return None

        args = [command, "-u", username, "--all"]
        if self._settings.github_auth_username and self._settings.github_token:
            args.extend(["--auth-user", self._settings.github_auth_username, "--token", self._settings.github_token])

        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self._settings.github_email_scraper_timeout_seconds,
            )
        except (OSError, asyncio.TimeoutError):
            return None

        output = stdout.decode("utf-8", errors="ignore")
        if not output:
            return None

        emails = EMAIL_PATTERN.findall(output)
        if not emails:
            return None

        for email in emails:
            lowered = email.lower()
            if lowered.endswith("@users.noreply.github.com"):
                continue
            return email

        return emails[0]
