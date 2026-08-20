from __future__ import annotations

import json
import re
from html import escape
from textwrap import dedent
from typing import Any

import httpx

from app.config import Settings
from app.models import GitHubRepository, GitHubScrapeResult

# This acts as the intelligence layer. It combines all the collected information and builds a structured understanding of the developer before passing it to the LLM.

class OnboardingEmailGenerator:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @staticmethod
    def generate_subject(github_username: str) -> str:
        return f"Welcome to Superplane, {github_username} 👋"

    async def generate_email(self, scrape_result: GitHubScrapeResult, repository_full_name: str) -> str:
        llm_payload = await self._generate_llm_payload(scrape_result, repository_full_name)
        if llm_payload is None:
            llm_payload = self._fallback_payload(scrape_result)
        return self._render_html_email(scrape_result, llm_payload)

    def generate_fallback_email(self, scrape_result: GitHubScrapeResult) -> str:
        return self._render_html_email(scrape_result, self._fallback_payload(scrape_result))

    async def _generate_llm_payload(
        self,
        scrape_result: GitHubScrapeResult,
        repository_full_name: str,
    ) -> dict[str, Any] | None:
        if not self._settings.openrouter_api_key:
            return None

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
                                "You create highly personalized developer onboarding email plans from public GitHub data. "
                                "Return valid JSON only."
                            ),
                        },
                        {
                            "role": "user",
                            "content": self._build_prompt(scrape_result, repository_full_name),
                        },
                    ],
                    "temperature": 0.5,
                    "max_tokens": 500,
                },
            )
            try:
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError):
                return None

        content = self._extract_message_text(payload)
        if not content:
            return None
        return self._parse_llm_json(content)

    def _build_prompt(self, scrape_result: GitHubScrapeResult, repository_full_name: str) -> str:
        profile = scrape_result.profile
        analysis = scrape_result.analysis
        repo_lines = []
        for repo in scrape_result.repositories[:8]:
            repo_lines.append(
                f"- {repo.full_name} | language={repo.language or 'Unknown'} | "
                f"stars={repo.stargazers_count} | description={repo.description or 'n/a'}"
            )

        pinned_repo_lines = []
        for repo in scrape_result.pinned_repositories[:6]:
            pinned_repo_lines.append(
                f"- {repo.full_name} | language={repo.language or 'Unknown'} | description={repo.description or 'n/a'}"
            )

        issue_lines = []
        for issue in scrape_result.candidate_issues[:8]:
            issue_lines.append(
                f"- {issue.title} | labels={', '.join(issue.labels) or 'none'} | url={issue.html_url}"
            )

        return dedent(
            f"""
            Create a personalized onboarding email plan for a GitHub user who starred {repository_full_name}.

            User profile:
            - login: {profile.login}
            - name: {profile.name or 'n/a'}
            - bio: {profile.bio or 'n/a'}
            - company: {profile.company or 'n/a'}
            - location: {profile.location or 'n/a'}
            - blog: {profile.blog or 'n/a'}
            - public email: {profile.email or 'not public'}
            - profile summary: {(profile.profile_summary or 'n/a')[:1200]}
            - profile readme excerpt: {(profile.profile_readme or 'n/a')[:3000]}
            - inferred interests: {', '.join(profile.inferred_interests) or 'n/a'}
            - personalization clues: {json.dumps(profile.personalization_clues)}
            - followers: {profile.followers}
            - following: {profile.following}
            - public repos: {profile.public_repos}

            Structured analysis:
            - primary languages: {', '.join(analysis.primary_languages) or 'n/a'}
            - language distribution: {json.dumps(analysis.language_distribution)}
            - top topics: {', '.join(analysis.top_topics) or 'n/a'}
            - project types: {', '.join(analysis.project_types) or 'n/a'}
            - profile strengths: {json.dumps(analysis.profile_strengths)}
            - contribution fit: {json.dumps(analysis.contribution_fit)}
            - notable repositories: {', '.join(analysis.notable_repositories) or 'n/a'}
            - activity summary: {analysis.activity_summary or 'n/a'}
            - evidence: {json.dumps(analysis.evidence)}
            - data quality: {analysis.data_quality}

            Public repositories:
            {chr(10).join(repo_lines) if repo_lines else '- none found'}

            Pinned repositories:
            {chr(10).join(pinned_repo_lines) if pinned_repo_lines else '- none found'}

            Candidate issues in the starred repository:
            {chr(10).join(issue_lines) if issue_lines else '- no open issues available'}

            Return JSON with exactly this shape:
            {{
              "observation": "One warm sentence that references 2-3 specific public themes from the user's profile, not just a language.",
              "frontend": ["bullet 1", "bullet 2", "bullet 3"],
              "documentation": ["bullet 1", "bullet 2", "bullet 3"],
              "beginner": ["bullet 1", "bullet 2", "bullet 3"],
              "starter_path": "One short path sentence tailored to the person."
            }}

            Rules:
            - Mention only publicly visible information.
            - Be specific and human.
            - Avoid generic wording like "based on your interest in TypeScript" unless there are no richer signals.
            - The three bullet groups should feel tailored to the user's actual projects, README, and profile signals.
            - Keep each bullet under 14 words.
            """
        ).strip()

    def _fallback_payload(self, scrape_result: GitHubScrapeResult) -> dict[str, Any]:
        return {
            "observation": self._build_observation(scrape_result),
            "frontend": self._frontend_lines(scrape_result),
            "documentation": self._docs_lines(scrape_result),
            "beginner": self._beginner_lines(scrape_result),
            "starter_path": self._starter_path(scrape_result),
        }

    def _build_observation(self, scrape_result: GitHubScrapeResult) -> str:
        clues = self._highlight_clues(scrape_result)
        if len(clues) >= 3:
            return (
                f"I noticed public themes around {clues[0]}, {clues[1]}, and {clues[2]} across your GitHub profile, "
                "so I picked contribution ideas that feel close to the way you already build and share work."
            )
        if len(clues) == 2:
            return (
                f"I noticed public themes around {clues[0]} and {clues[1]} across your GitHub profile, "
                "so the ideas below lean into those strengths."
            )
        if len(clues) == 1:
            return f"I noticed your public GitHub presence highlights {clues[0]}, so I tailored the ideas below in that direction."

        analysis = scrape_result.analysis
        if analysis.project_types and analysis.primary_languages:
            return (
                f"Your public repositories point toward {analysis.project_types[0]} work, with visible use of "
                f"{', '.join(analysis.primary_languages[:2])}, so I tailored these ideas around practical contribution paths."
            )
        if analysis.profile_strengths:
            return f"Your public GitHub profile suggests {analysis.profile_strengths[0].lower()}, so I tailored the ideas below around that signal."

        top_language = self._pick_top_language(scrape_result)
        if top_language:
            return (
                f"Your public repositories suggest a strong connection to {top_language}, so I centered these ideas around practical ways to contribute quickly."
            )
        return "I used the public signals from your GitHub profile to tailor the contribution ideas below."

    def _highlight_clues(self, scrape_result: GitHubScrapeResult) -> list[str]:
        profile = scrape_result.profile
        clues: list[str] = []

        for clue in profile.personalization_clues:
            normalized = self._normalize_clue(clue)
            if normalized:
                clues.append(normalized)

        for repo in scrape_result.pinned_repositories[:3]:
            if repo.description:
                clues.append(self._normalize_clue(repo.description))
            elif repo.name:
                clues.append(self._normalize_clue(repo.name.replace("-", " ")))

        for strength in scrape_result.analysis.profile_strengths[:2]:
            clues.append(self._normalize_clue(strength))

        clean = []
        seen: set[str] = set()
        for clue in clues:
            if not clue:
                continue
            lowered = clue.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            clean.append(clue)
        return clean[:3]

    @staticmethod
    def _normalize_clue(clue: str | None) -> str | None:
        if not clue:
            return None
        value = re.sub(r"^(README focus:|Pinned project:)\s*", "", clue, flags=re.IGNORECASE).strip()
        value = re.sub(r"\s+", " ", value)
        if len(value) < 4:
            return None
        return value[:90]

    def _interest_corpus(self, scrape_result: GitHubScrapeResult) -> str:
        profile = scrape_result.profile
        repo_bits = []
        for repo in [*scrape_result.repositories[:10], *scrape_result.pinned_repositories[:6]]:
            repo_bits.append(" ".join(filter(None, [repo.name, repo.description, repo.language, " ".join(repo.topics)])))
        return " ".join(
            filter(
                None,
                [
                    profile.bio,
                    profile.profile_summary,
                    profile.profile_readme,
                    " ".join(profile.inferred_interests),
                    " ".join(profile.personalization_clues),
                    " ".join(scrape_result.analysis.primary_languages),
                    " ".join(scrape_result.analysis.top_topics),
                    " ".join(scrape_result.analysis.project_types),
                    " ".join(scrape_result.analysis.profile_strengths),
                    " ".join(scrape_result.analysis.contribution_fit),
                    " ".join(repo_bits),
                ],
            )
        ).lower()

    def _frontend_lines(self, scrape_result: GitHubScrapeResult) -> list[str]:
        corpus = self._interest_corpus(scrape_result)
        top_language = (self._pick_top_language(scrape_result) or "").lower()
        if any("frontend" in fit.lower() or "ui" in fit.lower() for fit in scrape_result.analysis.contribution_fit):
            return [
                "Improve workflow UI states around runs and approvals",
                "Polish contributor-facing screens with clearer defaults",
                "Tighten reusable frontend components for workflow setup",
            ]
        if any(keyword in corpus for keyword in ("design", "ui", "ux", "frontend", "react", "next.js", "component")):
            return [
                "Refine dashboard flows with clearer interaction states",
                "Polish contributor-facing UI patterns and reusable components",
                "Improve onboarding screens with more intentional visual guidance",
            ]
        if any(keyword in corpus for keyword in ("community", "portfolio", "personal brand", "showcase")):
            return [
                "Improve first-impression UI around the dashboard and workflow canvas",
                "Tighten small product details that make the app easier to explore",
                "Polish contributor cards, empty states, and discovery surfaces",
            ]
        if top_language in {"typescript", "javascript"}:
            return [
                "Strengthen TypeScript-driven UI flows across the dashboard",
                "Improve reusable frontend components and developer ergonomics",
                "Tighten onboarding and empty-state experiences for new users",
            ]
        return [
            "Improve dashboard components",
            "Polish contributor cards",
            "Improve empty states and onboarding screens",
        ]

    def _docs_lines(self, scrape_result: GitHubScrapeResult) -> list[str]:
        corpus = self._interest_corpus(scrape_result)
        if any("documentation" in fit.lower() or "examples" in fit.lower() for fit in scrape_result.analysis.contribution_fit):
            return [
                "Add focused examples for real workflow automation scenarios",
                "Improve first-run docs with clearer environment setup",
                "Document small contribution paths by skill area",
            ]
        if any(keyword in corpus for keyword in ("documentation", "docs", "guide", "tutorial", "community", "teaching", "learning", "mentoring")):
            return [
                "Add clearer setup walkthroughs with annotated screenshots",
                "Improve first-contributor docs for local workflow setup",
                "Create practical examples that explain workflows step by step",
            ]
        if any(keyword in corpus for keyword in ("portfolio", "content", "blog", "readme")):
            return [
                "Improve contributor docs with cleaner examples and context",
                "Add setup screenshots that reduce first-run confusion",
                "Make onboarding docs easier to skim and act on",
            ]
        return [
            "Add setup screenshots",
            "Improve local development docs",
            "Create beginner-friendly examples",
        ]

    def _beginner_lines(self, scrape_result: GitHubScrapeResult) -> list[str]:
        corpus = self._interest_corpus(scrape_result)
        if scrape_result.analysis.contribution_fit:
            return [
                f"Start with {scrape_result.analysis.contribution_fit[0].lower()}",
                "Pick a contained issue with a clear before-and-after",
                "Use docs or tests to validate the first change",
            ]
        if any(keyword in corpus for keyword in ("automation", "workflow", "bot", "scraping", "agent", "integration")):
            return [
                "Improve workflow labels, helper text, and run-state messaging",
                "Tighten contributor-facing feedback around automation edges",
                "Start with low-risk workflow polish while learning the system",
            ]
        if any(keyword in corpus for keyword in ("python", "backend", "api", "fastapi", "server")):
            return [
                "Improve small API-facing error messages and responses",
                "Fix onboarding gaps that help contributors run things locally",
                "Pick low-risk product polish issues while learning the workflow model",
            ]
        if any(keyword in corpus for keyword in ("community", "opensource", "hacktoberfest", "contributor")):
            return [
                "Start with README, docs, or issue-label polish",
                "Improve first-contribution guidance and small UX rough edges",
                "Tackle low-risk fixes that help new contributors feel confident",
            ]
        return [
            "Fix typos in README or docs",
            "Improve error messages",
            "Add small UI improvements",
        ]

    def _starter_path(self, scrape_result: GitHubScrapeResult) -> str:
        corpus = self._interest_corpus(scrape_result)
        analysis = scrape_result.analysis
        if analysis.contribution_fit and analysis.notable_repositories:
            return (
                f"Start by mapping your experience from {analysis.notable_repositories[0]} to "
                f"{analysis.contribution_fit[0].lower()}, then pick a small issue with visible user impact."
            )
        if any(keyword in corpus for keyword in ("documentation", "guide", "tutorial", "teaching")):
            return "Start by reading the docs, run a sample workflow, then pick a docs or onboarding issue before moving into code."
        if any(keyword in corpus for keyword in ("automation", "workflow", "bot", "agent")):
            return "Start by understanding the workflow model, run a sample flow, then pick a small automation-facing issue to learn the codebase."
        if any(keyword in corpus for keyword in ("ui", "frontend", "react", "next.js", "design")):
            return "Start by exploring the product UI, run a sample workflow, then pick a small frontend polish issue for your first PR."
        return "Start with the basics, run a sample workflow, explore the codebase, then pick one small issue to ship confidently."

    def _render_html_email(self, scrape_result: GitHubScrapeResult, payload: dict[str, Any]) -> str:
        profile = scrape_result.profile
        observation = escape(str(payload.get("observation") or self._build_observation(scrape_result)))
        frontend = self._normalize_three(payload.get("frontend"), self._frontend_lines(scrape_result))
        documentation = self._normalize_three(payload.get("documentation"), self._docs_lines(scrape_result))
        beginner = self._normalize_three(payload.get("beginner"), self._beginner_lines(scrape_result))
        starter_path = escape(str(payload.get("starter_path") or self._starter_path(scrape_result)))
        highlight_clues = self._highlight_clues(scrape_result)

        clue_html = ""
        if highlight_clues:
            clue_html = "".join(
                f'<span style="display:inline-block;margin:0 8px 8px 0;padding:8px 12px;border-radius:999px;background:#eef6ff;color:#174ea6;font-size:13px;font-weight:600;">{escape(clue)}</span>'
                for clue in highlight_clues
            )

        return f"""\
<!DOCTYPE html>
<html>
  <body style="margin:0;padding:0;background:#f4f7fb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:#132238;">
    <div style="max-width:720px;margin:0 auto;padding:32px 20px;">
      <div style="background:#ffffff;border:1px solid #dce6f2;border-radius:24px;overflow:hidden;box-shadow:0 14px 42px rgba(19,34,56,0.08);">
        <div style="padding:36px 36px 28px;background:linear-gradient(135deg,#0f172a 0%,#1e3a8a 58%,#0ea5e9 100%);color:#ffffff;">
          <div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;opacity:0.82;margin-bottom:14px;">Superplane community</div>
          <h1 style="margin:0 0 14px;font-size:30px;line-height:1.2;font-weight:800;">Hey {escape(profile.login)} 👋</h1>
          <p style="margin:0;font-size:16px;line-height:1.7;max-width:580px;color:rgba(255,255,255,0.92);">
            Thanks for starring Superplane. We're excited to have you here.
          </p>
        </div>

        <div style="padding:32px 36px;">
          <p style="margin:0 0 18px;font-size:16px;line-height:1.75;color:#304256;">
            Superplane is an open-source platform for building and coordinating engineering workflows — from CI/CD pipelines and deployment approvals to incident automation and human-in-the-loop operations.
          </p>

          <div style="margin:0 0 18px;padding:18px 20px;border-radius:18px;background:#f8fbff;border:1px solid #d9e8fb;">
            <p style="margin:0;font-size:15px;line-height:1.75;color:#23405f;">
              {observation}
            </p>
          </div>

          {f'<div style="margin:0 0 10px;">{clue_html}</div>' if clue_html else ''}

          <h2 style="margin:26px 0 16px;font-size:22px;line-height:1.3;color:#0f172a;">Where you might enjoy contributing</h2>

          {self._section_card("1. Frontend / UI", frontend)}
          {self._section_card("2. Documentation", documentation)}
          {self._section_card("3. Beginner-friendly issues", beginner)}

          <h2 style="margin:28px 0 14px;font-size:22px;line-height:1.3;color:#0f172a;">Recommended first steps</h2>
          <ol style="margin:0 0 20px 22px;padding:0;color:#23364d;font-size:15px;line-height:1.9;">
            <li><a href="https://github.com/superplanehq/superplane" style="color:#155eef;text-decoration:none;">Explore the repository</a></li>
            <li><a href="https://github.com/superplanehq/superplane/blob/main/CONTRIBUTING.md" style="color:#155eef;text-decoration:none;">Read the contribution guide</a></li>
            <li><a href="https://github.com/superplanehq/superplane/issues" style="color:#155eef;text-decoration:none;">Pick a good first issue</a></li>
            <li>Comment on the issue: <span style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#0f172a;">“I'd like to work on this.”</span></li>
            <li><a href="https://community-coral-nu.vercel.app" style="color:#155eef;text-decoration:none;">Join the community learning page</a></li>
          </ol>

          <div style="margin:0 0 22px;padding:20px;border-radius:18px;background:#fff7ed;border:1px solid #fed7aa;">
            <div style="font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:#9a3412;font-weight:700;margin-bottom:8px;">Suggested starter path for you</div>
            <div style="font-size:15px;line-height:1.75;color:#7c2d12;">{starter_path}</div>
          </div>

          <div style="margin:0 0 22px;padding:20px;border-radius:18px;background:#f8fafc;border:1px solid #e2e8f0;">
            <div style="font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:#475569;font-weight:700;margin-bottom:10px;">On the community page, you'll find</div>
            <ul style="margin:0;padding-left:20px;color:#334155;font-size:15px;line-height:1.8;">
              <li>Beginner-friendly tutorials</li>
              <li>Superplane workflow examples</li>
              <li>Contribution guidance</li>
              <li>Lessons to understand how Superplane works</li>
              <li>A playground to learn by building workflows</li>
            </ul>
          </div>

          <p style="margin:0 0 18px;font-size:15px;line-height:1.8;color:#304256;">
            If you get stuck, don’t worry. Start small, ask questions, and focus on making one helpful contribution.
          </p>
          <p style="margin:0;font-size:15px;line-height:1.8;color:#304256;">
            Welcome again, excited to see what you build with Superplane 🚀
          </p>

          <div style="margin-top:28px;padding-top:22px;border-top:1px solid #e5edf5;color:#475569;font-size:14px;line-height:1.7;">
            <div style="font-weight:700;color:#0f172a;">Best,</div>
            <div>The Superplane community</div>
          </div>
        </div>
      </div>
    </div>
  </body>
</html>
"""

    @staticmethod
    def _section_card(title: str, items: list[str]) -> str:
        bullet_items = "".join(
            f'<li style="margin:0 0 10px;">{escape(item)}</li>'
            for item in items[:3]
        )
        return f"""
        <div style="margin:0 0 16px;padding:20px;border-radius:18px;background:#ffffff;border:1px solid #e5edf5;">
          <div style="font-size:17px;font-weight:700;color:#0f172a;margin-bottom:12px;">{escape(title)}</div>
          <ul style="margin:0;padding-left:20px;color:#334155;font-size:15px;line-height:1.75;">
            {bullet_items}
          </ul>
        </div>
        """

    @staticmethod
    def _normalize_three(value: Any, fallback: list[str]) -> list[str]:
        if isinstance(value, list):
            cleaned = [str(item).strip() for item in value if str(item).strip()]
            if len(cleaned) >= 3:
                return cleaned[:3]
        return fallback[:3]

    @staticmethod
    def _pick_top_language(scrape_result: GitHubScrapeResult) -> str | None:
        counts: dict[str, int] = {}
        for repo in [*scrape_result.repositories, *scrape_result.pinned_repositories]:
            if repo.language:
                counts[repo.language] = counts.get(repo.language, 0) + 1
        if not counts:
            return None
        return max(counts, key=counts.get)

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

    @staticmethod
    def _parse_llm_json(content: str) -> dict[str, Any] | None:
        text = content.strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            text = match.group(0)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return payload


def repositories_summary(repositories: list[GitHubRepository]) -> list[str]:
    return [repo.full_name for repo in repositories[:5]]
