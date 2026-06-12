from __future__ import annotations

import asyncio
import re
from collections import Counter

import httpx
from scrapy import Selector

# So this component analyzes the developer's public GitHub repositories. It scrapes the profile page and the optional profile README to extract information about the developer's interests, skills, and projects. This is done using the Scrapy library to parse the HTML content of the GitHub pages. The extracted information is then used to generate a profile summary, infer interests, and identify personalization clues that can be used in onboarding emails or other communications.

_INTEREST_KEYWORDS = {
    "frontend": ("frontend", "ui", "ux", "react", "next.js", "javascript", "typescript", "css", "tailwind"),
    "backend": ("backend", "api", "fastapi", "django", "flask", "node", "express", "database", "microservice"),
    "devops": ("devops", "ci/cd", "docker", "kubernetes", "terraform", "aws", "deployment", "pipeline"),
    "automation": ("automation", "workflow", "bot", "agent", "scraping", "crawler", "integration"),
    "documentation": ("documentation", "docs", "tutorial", "guide", "readme", "example"),
    "data": ("data", "analytics", "machine learning", "ai", "llm", "python", "notebook", "visualization"),
    "mobile": ("android", "ios", "flutter", "react native", "mobile"),
    "opensource": ("open source", "community", "contributor", "hacktoberfest"),
}

_GENERIC_HEADINGS = {
    "about me",
    "about",
    "connect with me",
    "tech stack",
    "skills",
    "stats",
    "github stats",
    "reach me",
    "contact",
}


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _unique_non_empty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        normalized = _clean_text(value)
        lowered = normalized.lower()
        if not normalized or lowered in seen:
            continue
        seen.add(lowered)
        cleaned.append(normalized)
    return cleaned


class ScrapyGitHubProfileScraper:
    def __init__(self) -> None:
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            )
        }

    async def scrape(self, username: str) -> dict[str, object]:
        profile_url = f"https://github.com/{username}"
        readme_url = f"https://github.com/{username}/{username}"

        async with httpx.AsyncClient(headers=self._headers, follow_redirects=True, timeout=20.0) as client:
            profile_response, readme_response = await asyncio.gather(
                client.get(profile_url),
                client.get(readme_url),
            )

        profile_response.raise_for_status()
        profile_selector = Selector(text=profile_response.text)

        readme_selector: Selector | None = None
        if readme_response.status_code == 200:
            readme_selector = Selector(text=readme_response.text)

        bio = _clean_text(" ".join(profile_selector.css('[data-bio-text]::text, .p-note.user-profile-bio div::text').getall()))
        about_items = _unique_non_empty(profile_selector.css(".js-profile-editable-area .vcard-details span::text, .js-profile-editable-area .vcard-details a::text").getall())

        pinned_repositories = []
        for item in profile_selector.css('li[class*="pinned-item-list-item"], div[data-testid="pinned-items-reorder-container"] li'):
            title = _clean_text(" ".join(item.css("span.repo::text, a span::text").getall()))
            description = _clean_text(" ".join(item.css("p::text").getall())) or None
            language = _clean_text(" ".join(item.css('span[itemprop="programmingLanguage"]::text, span[style*="background-color"] + span::text').getall())) or None
            if title:
                pinned_repositories.append(
                    {
                        "name": title.split("/")[-1],
                        "full_name": title if "/" in title else f"{username}/{title}",
                        "description": description,
                        "html_url": f"https://github.com/{title}" if "/" in title else f"https://github.com/{username}/{title}",
                        "language": language,
                    }
                )

        readme_lines: list[str] = []
        readme_headings: list[str] = []
        if readme_selector is not None:
            readme_headings = _unique_non_empty(
                readme_selector.css("article.markdown-body h1::text, article.markdown-body h2::text, article.markdown-body h3::text").getall()
            )
            readme_lines = _unique_non_empty(
                readme_selector.css(
                    "article.markdown-body p::text, article.markdown-body li::text, article.markdown-body blockquote p::text"
                ).getall()
            )

        summary_parts = []
        if bio:
            summary_parts.append(bio)
        if about_items:
            summary_parts.append(" | ".join(about_items[:6]))
        if readme_headings:
            summary_parts.append("README sections: " + ", ".join(readme_headings[:8]))
        profile_summary = " ".join(summary_parts)[:1200] or None

        interests = self._infer_interests(
            bio=bio,
            about_items=about_items,
            readme_headings=readme_headings,
            readme_lines=readme_lines,
            pinned_repositories=pinned_repositories,
        )
        personalization_clues = self._extract_personalization_clues(
            bio=bio,
            about_items=about_items,
            readme_headings=readme_headings,
            readme_lines=readme_lines,
            pinned_repositories=pinned_repositories,
        )

        readme_excerpt = "\n".join(readme_lines[:30])[:5000] or None

        return {
            "profile_summary": profile_summary,
            "readme_excerpt": readme_excerpt,
            "interests": interests,
            "personalization_clues": personalization_clues,
            "pinned_repositories": pinned_repositories,
        }

    def _infer_interests(
        self,
        *,
        bio: str,
        about_items: list[str],
        readme_headings: list[str],
        readme_lines: list[str],
        pinned_repositories: list[dict[str, str | None]],
    ) -> list[str]:
        corpus_parts = [bio, *about_items, *readme_headings, *readme_lines[:20]]
        for repo in pinned_repositories[:6]:
            corpus_parts.extend(
                [
                    repo.get("name") or "",
                    repo.get("description") or "",
                    repo.get("language") or "",
                ]
            )

        corpus = " ".join(corpus_parts).lower()
        matched: list[str] = []
        for interest, keywords in _INTEREST_KEYWORDS.items():
            if any(keyword in corpus for keyword in keywords):
                matched.append(interest)

        if matched:
            return matched[:6]

        token_counter: Counter[str] = Counter(
            token
            for token in re.findall(r"[a-zA-Z][a-zA-Z0-9+.#-]{2,}", corpus)
            if token not in {"with", "from", "that", "this", "your", "have", "into", "github", "build", "developer"}
        )
        return [token for token, _ in token_counter.most_common(6)]

    def _extract_personalization_clues(
        self,
        *,
        bio: str,
        about_items: list[str],
        readme_headings: list[str],
        readme_lines: list[str],
        pinned_repositories: list[dict[str, str | None]],
    ) -> list[str]:
        clues: list[str] = []

        if bio:
            clues.append(bio)

        for item in about_items:
            if len(item) > 4:
                clues.append(item)

        for heading in readme_headings:
            normalized = heading.strip().lower()
            if normalized and normalized not in _GENERIC_HEADINGS:
                clues.append(f"README focus: {heading}")

        for line in readme_lines[:15]:
            normalized = line.strip()
            lowered = normalized.lower()
            if len(normalized) < 12:
                continue
            if any(term in lowered for term in ("building", "working on", "interested in", "love", "passionate", "focused on", "currently")):
                clues.append(normalized)

        for repo in pinned_repositories[:4]:
            description = (repo.get("description") or "").strip()
            if description:
                clues.append(f"Pinned project: {description}")
            elif repo.get("name"):
                clues.append(f"Pinned project: {repo['name']}")

        return _unique_non_empty(clues)[:8]
