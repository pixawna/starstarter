from __future__ import annotations

from textwrap import dedent
from typing import Any

import httpx

from app.config import Settings
from app.models import GitHubScrapeResult


class OnboardingEmailGenerator:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @staticmethod
    def generate_subject(github_username: str) -> str:
        return f"Welcome to Superplane, {github_username} 👋"

    async def generate_email(self, scrape_result: GitHubScrapeResult, repository_full_name: str) -> str:
        if not self._settings.openrouter_api_key:
            return self._fallback_email(scrape_result)

        async with httpx.AsyncClient(
            base_url=self._settings.openrouter_base_url,
            timeout=self._settings.openrouter_timeout_seconds,
            headers={
                "Authorization": f"Bearer {self._settings.openrouter_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": self._settings.app_url or "http://localhost:8000",
                "X-Title": self._settings.app_name,
            },
        ) as client:
            response = await client.post(
                "/chat/completions",
                json={
                    "model": self._settings.openrouter_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You write concise, warm onboarding emails for developers who starred an open-source repo. "
                                "Return plain text only."
                            ),
                        },
                        {
                            "role": "user",
                            "content": self._build_prompt(scrape_result, repository_full_name),
                        },
                    ],
                    "temperature": 0.4,
                    "max_tokens": 220,
                },
            )
            try:
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError):
                return self._fallback_email(scrape_result)

        content = self._extract_message_text(payload)
        if not content:
            return self._fallback_email(scrape_result)
        return content.strip()

    def _build_prompt(self, scrape_result: GitHubScrapeResult, repository_full_name: str) -> str:
        profile = scrape_result.profile
        repo_lines = []
        for repo in scrape_result.repositories[:8]:
            repo_lines.append(
                f"- {repo.full_name} | language={repo.language or 'Unknown'} | "
                f"stars={repo.stargazers_count} | description={repo.description or 'n/a'}"
            )

        issue_lines = []
        for issue in scrape_result.candidate_issues[:8]:
            issue_lines.append(
                f"- {issue.title} | labels={', '.join(issue.labels) or 'none'} | url={issue.html_url}"
            )

        return dedent(
            f"""
            Create a personalized onboarding email for a GitHub user who starred {repository_full_name}.

            User profile:
            - login: {profile.login}
            - name: {profile.name or 'n/a'}
            - bio: {profile.bio or 'n/a'}
            - company: {profile.company or 'n/a'}
            - location: {profile.location or 'n/a'}
            - blog: {profile.blog or 'n/a'}
            - public email: {profile.email or 'not public'}
            - profile readme: {(profile.profile_readme or 'n/a')[:2500]}
            - followers: {profile.followers}
            - following: {profile.following}
            - public repos: {profile.public_repos}

            Public repositories:
            {chr(10).join(repo_lines) if repo_lines else '- none found'}

            Candidate issues in the starred repository:
            {chr(10).join(issue_lines) if issue_lines else '- no open issues available'}

            Requirements:
            - Start with "Hey <github_login> 👋"
            - Thank the user for starring Superplane.
            - Briefly explain that Superplane is an open-source platform for building and coordinating engineering workflows.
            - Recommend exactly 3 contribution areas tailored to the user's public GitHub profile.
            - Use the user's repository history, bio, languages, and profile README when available.
            - Use this structure: Frontend / UI, Documentation, Beginner-friendly issues.
            - Include a "Recommended first steps:" section with these exact links:
              1. https://github.com/superplanehq/superplane
              2. https://github.com/superplanehq/superplane/blob/main/CONTRIBUTING.md
              3. https://github.com/superplanehq/superplane/issues
              4. Comment on the issue: "I'd like to work on this."
              5. https://community-coral-nu.vercel.app
            - Include a short "Suggested starter path for you:" line.
            - End warmly as The Superplane community.
            - Keep it plain text, concise, friendly, and action-oriented.
            - Mention only publicly visible information.
            """
        ).strip()

    def _fallback_email(self, scrape_result: GitHubScrapeResult) -> str:
        profile = scrape_result.profile
        top_language = self._pick_top_language(scrape_result)
        frontend_lines = self._personalized_lines(
            scrape_result,
            default_lines=[
                "Improve dashboard components",
                "Polish contributor cards",
                "Improve empty states and onboarding screens",
            ],
            keywords=("frontend", "react", "ui", "design", "typescript", "javascript"),
        )
        docs_lines = self._personalized_lines(
            scrape_result,
            default_lines=[
                "Add setup screenshots",
                "Improve local development docs",
                "Create beginner-friendly examples",
            ],
            keywords=("docs", "documentation", "tutorial", "guide"),
        )
        beginner_lines = self._personalized_lines(
            scrape_result,
            default_lines=[
                "Fix typos in README or docs",
                "Improve error messages",
                "Add small UI improvements",
            ],
            keywords=("beginner", "good first issue", "readme", "error"),
        )
        intro = (
            f"Based on your public GitHub profile{f' and your interest in {top_language}' if top_language else ''}, "
            "you might enjoy contributing to areas like:"
        )

        lines = [
            f"Hey {profile.login} 👋",
            "",
            "Thanks for starring Superplane. We're excited to have you here.",
            "",
            "Superplane is an open-source platform for building and coordinating engineering workflows — from CI/CD pipelines and deployment approvals to incident automation and human-in-the-loop operations.",
            "",
            intro,
            "",
            "1. Frontend / UI",
            f"   - {frontend_lines[0]}",
            f"   - {frontend_lines[1]}",
            f"   - {frontend_lines[2]}",
            "",
            "2. Documentation",
            f"   - {docs_lines[0]}",
            f"   - {docs_lines[1]}",
            f"   - {docs_lines[2]}",
            "",
            "3. Beginner-friendly issues",
            f"   - {beginner_lines[0]}",
            f"   - {beginner_lines[1]}",
            f"   - {beginner_lines[2]}",
            "",
            "Recommended first steps:",
            "",
            "1. Explore the repository",
            "   https://github.com/superplanehq/superplane",
            "",
            "2. Read the contribution guide",
            "   https://github.com/superplanehq/superplane/blob/main/CONTRIBUTING.md",
            "",
            "3. Pick a good first issue",
            "   https://github.com/superplanehq/superplane/issues",
            "",
            '4. Comment on the issue',
            '   "I\'d like to work on this."',
            "",
            "5. Join the community learning page",
            "   https://community-coral-nu.vercel.app",
            "",
            "On the community page, you'll find:",
            "- Beginner-friendly tutorials",
            "- Superplane workflow examples",
            "- Contribution guidance",
            "- Lessons to understand how Superplane works",
            "- A playground to learn by building workflows",
            "",
            "Suggested starter path for you:",
            "",
            '"Understand Superplane basics -> Run a sample workflow -> Explore the codebase -> Pick your first issue -> Submit your first PR."',
            "",
            "If you get stuck, don't worry. Start small, ask questions, and focus on making one helpful contribution.",
            "",
            "Welcome again, excited to see what you build with Superplane 🚀",
            "",
            "Best,",
            "The Superplane community",
        ]
        return "\n".join(lines)

    @staticmethod
    def _pick_top_language(scrape_result: GitHubScrapeResult) -> str | None:
        counts: dict[str, int] = {}
        for repo in scrape_result.repositories:
            if repo.language:
                counts[repo.language] = counts.get(repo.language, 0) + 1
        if not counts:
            return None
        return max(counts, key=counts.get)

    @staticmethod
    def _personalized_lines(
        scrape_result: GitHubScrapeResult,
        default_lines: list[str],
        keywords: tuple[str, ...],
    ) -> list[str]:
        suggestions: list[str] = []
        searchable_text = []
        for repo in scrape_result.repositories[:10]:
            searchable_text.append(" ".join(filter(None, [repo.name, repo.description, repo.language, " ".join(repo.topics)])))
        joined = " ".join(searchable_text).lower()

        for keyword in keywords:
            if keyword in joined:
                if keyword in {"react", "ui", "design", "frontend"}:
                    suggestions = [
                        "Improve dashboard components",
                        "Polish contributor cards",
                        "Improve empty states and onboarding screens",
                    ]
                    break
                if keyword in {"docs", "documentation", "tutorial", "guide"}:
                    suggestions = [
                        "Add setup screenshots",
                        "Improve local development docs",
                        "Create beginner-friendly examples",
                    ]
                    break
                if keyword in {"beginner", "good first issue", "readme", "error"}:
                    suggestions = [
                        "Fix typos in README or docs",
                        "Improve error messages",
                        "Add small UI improvements",
                    ]
                    break

        return suggestions or default_lines

    @staticmethod
    def _extract_message_text(payload: dict[str, Any]) -> str | None:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return None

        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            return "".join(parts) or None
        return None
