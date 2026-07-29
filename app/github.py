from __future__ import annotations

import asyncio
import base64
from typing import Any

import httpx

from app.config import Settings
from app.email_scraper import GitHubEmailScraperClient
from app.models import (
    GitHubRepository,
    GitHubScrapeResult,
    GitHubUserProfile,
    RepositoryIssue,
)
from app.scrapy_profile_scraper import ScrapyGitHubProfileScraper

# This module is responsible for interacting with the GitHub API to fetch user profiles, repositories, and issues. It also integrates with the GitHubEmailScraperClient and ScrapyGitHubProfileScraper to enrich the data it collects from GitHub.

class GitHubClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._email_scraper = GitHubEmailScraperClient(settings)
        self._scrapy_profile_scraper = ScrapyGitHubProfileScraper()

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "starstarter-webhook",
        }
        if self._settings.github_token:
            headers["Authorization"] = f"Bearer {self._settings.github_token}"
        return headers

    async def _get_json(self, client: httpx.AsyncClient, path: str, params: dict[str, Any] | None = None) -> Any:
        response = await client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    async def _get_optional_profile_readme(self, client: httpx.AsyncClient, username: str) -> str | None:
        response = await client.get(f"/repos/{username}/{username}/readme")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        content = payload.get("content")
        if not content:
            return None
        try:
            decoded = base64.b64decode(content).decode("utf-8", errors="ignore")
        except Exception:
            return None
        return decoded[:6000] or None

    async def _safe_scrapy_profile_scrape(self, username: str) -> dict[str, object]:
        try:
            return await self._scrapy_profile_scraper.scrape(username)
        except Exception:
            return {
                "profile_summary": None,
                "readme_excerpt": None,
                "interests": [],
                "pinned_repositories": [],
            }

    async def scrape_user(self, username: str, target_repository_full_name: str) -> GitHubScrapeResult:
        async with httpx.AsyncClient(
            base_url=self._settings.github_api_base_url,
            headers=self._headers(),
            timeout=self._settings.http_timeout_seconds,
        ) as client:
            results = await asyncio.gather(
                self._get_json(client, f"/users/{username}"),
                self._get_json(
                    client,
                    f"/users/{username}/repos",
                    params={"sort": "updated", "per_page": 20, "type": "owner"},
                ),
                self._get_json(
                    client,
                    f"/repos/{target_repository_full_name}/issues",
                    params={"state": "open", "per_page": 10},
                ),
                self._get_optional_profile_readme(client, username),
                self._email_scraper.find_email(username),
                self._safe_scrapy_profile_scrape(username),
                return_exceptions=True,
            )

        profile_data = results[0] if isinstance(results[0], dict) else {"login": username}
        repos_data = results[1] if isinstance(results[1], list) else []
        issues_data = results[2] if isinstance(results[2], list) else []
        profile_readme = results[3] if isinstance(results[3], str) else None
        scraped_email = results[4] if isinstance(results[4], str) else None
        scraped_profile_data = results[5] if isinstance(results[5], dict) else {
            "profile_summary": None,
            "readme_excerpt": None,
            "interests": [],
            "personalization_clues": [],
            "pinned_repositories": [],
        }

        profile = GitHubUserProfile(
            login=str(profile_data.get("login") or username),
            name=profile_data.get("name"),
            bio=profile_data.get("bio"),
            company=profile_data.get("company"),
            location=profile_data.get("location"),
            blog=profile_data.get("blog"),
            email=profile_data.get("email") or scraped_email,
            profile_readme=profile_readme or scraped_profile_data.get("readme_excerpt"),
            profile_summary=scraped_profile_data.get("profile_summary"),
            inferred_interests=list(scraped_profile_data.get("interests") or []),
            personalization_clues=list(scraped_profile_data.get("personalization_clues") or []),
            public_repos=profile_data.get("public_repos", 0),
            followers=profile_data.get("followers", 0),
            following=profile_data.get("following", 0),
        )

        repositories = [
            GitHubRepository(
                name=repo["name"],
                full_name=repo["full_name"],
                description=repo.get("description"),
                html_url=repo["html_url"],
                language=repo.get("language"),
                stargazers_count=repo.get("stargazers_count", 0),
                forks_count=repo.get("forks_count", 0),
                topics=repo.get("topics") or [],
                updated_at=repo.get("updated_at"),
            )
            for repo in repos_data
        ]

        candidate_issues = []
        for issue in issues_data:
            if issue.get("pull_request"):
                continue
            candidate_issues.append(
                RepositoryIssue(
                    title=issue["title"],
                    html_url=issue["html_url"],
                    labels=[label["name"] for label in issue.get("labels", [])],
                    body=issue.get("body"),
                )
            )

        return GitHubScrapeResult(
            profile=profile,
            repositories=repositories,
            candidate_issues=candidate_issues,
            pinned_repositories=[
                GitHubRepository(
                    name=repo["name"],
                    full_name=repo["full_name"],
                    description=repo.get("description"),
                    html_url=repo["html_url"],
                    language=repo.get("language"),
                    stargazers_count=0,
                    forks_count=0,
                    topics=[],
                    updated_at=None,
                )
                for repo in scraped_profile_data.get("pinned_repositories", [])
                if repo.get("name") and repo.get("full_name") and repo.get("html_url")
            ],
        )
