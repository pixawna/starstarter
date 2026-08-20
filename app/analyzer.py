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
        return f"Superplane issues matched to your skills, {github_username}"

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
        for issue in scrape_result.candidate_issues[:5]:
            issue_lines.append(
                f"- #{issue.number or '?'} {issue.title} | fit_score={issue.fit_score} | "
                f"fit_reasons={'; '.join(issue.fit_reasons)} | labels={', '.join(issue.labels) or 'none'} | "
                f"url={issue.html_url} | body={(issue.body or 'n/a')[:500]}"
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
              "starter_path": "One short path sentence tailored to the person."
            }}

            Rules:
            - Mention only publicly visible information.
            - Be specific and human.
            - Avoid generic wording like "based on your interest in TypeScript" unless there are no richer signals.
            - Do not invent, rename, or recommend issues; ranked issues are rendered separately from GitHub data.
            - Explain the connection between their demonstrated work and the top-ranked issue.
            """
        ).strip()

    def _fallback_payload(self, scrape_result: GitHubScrapeResult) -> dict[str, Any]:
        return {
            "observation": self._build_observation(scrape_result),
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

    def _starter_path(self, scrape_result: GitHubScrapeResult) -> str:
        corpus = self._interest_corpus(scrape_result)
        analysis = scrape_result.analysis
        if scrape_result.candidate_issues:
            issue = scrape_result.candidate_issues[0]
            issue_reference = f"issue #{issue.number}" if issue.number else "the top recommended issue"
            if issue.matched_skills:
                return (
                    f"Start with {issue_reference}: its {issue.matched_skills[0]} focus is the closest match "
                    "to the skills visible in your public work."
                )
            return f"Start with {issue_reference}, reproduce the behavior locally, and confirm scope with a maintainer before coding."
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
        starter_path = escape(str(payload.get("starter_path") or self._starter_path(scrape_result)))
        highlight_clues = self._highlight_clues(scrape_result)
        analysis = scrape_result.analysis
        issue_cards = self._issue_cards(scrape_result)

        language_summary = ", ".join(analysis.primary_languages[:4]) or "Not enough public data"
        project_summary = ", ".join(analysis.project_types[:3]) or "General open-source work"
        repo_count = len(scrape_result.repositories)
        activity_summary = analysis.activity_summary or "Not enough public activity data"

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

          <h2 style="margin:26px 0 16px;font-size:22px;line-height:1.3;color:#0f172a;">What your public GitHub shows</h2>
          <div style="margin:0 0 22px;padding:20px;border-radius:18px;background:#f8fafc;border:1px solid #e2e8f0;">
            <div style="margin:0 0 8px;font-size:15px;line-height:1.6;color:#334155;"><strong style="color:#0f172a;">Languages:</strong> {escape(language_summary)}</div>
            <div style="margin:0 0 8px;font-size:15px;line-height:1.6;color:#334155;"><strong style="color:#0f172a;">Project strengths:</strong> {escape(project_summary)}</div>
            <div style="margin:0 0 8px;font-size:15px;line-height:1.6;color:#334155;"><strong style="color:#0f172a;">Profile metrics:</strong> {profile.public_repos} public repos · {profile.followers} followers</div>
            <div style="margin:0 0 8px;font-size:15px;line-height:1.6;color:#334155;"><strong style="color:#0f172a;">Activity:</strong> {escape(activity_summary)}</div>
            <div style="margin:0;font-size:15px;line-height:1.6;color:#334155;"><strong style="color:#0f172a;">Repos analyzed:</strong> {repo_count} <span style="color:#64748b;">(data quality: {escape(analysis.data_quality)})</span></div>
          </div>

          <h2 style="margin:26px 0 8px;font-size:22px;line-height:1.3;color:#0f172a;">Superplane issues matched to your skills</h2>
          <p style="margin:0 0 16px;font-size:14px;line-height:1.7;color:#64748b;">These are live open issues ranked from the public Superplane issue tracker. Fit is based on your public repositories, languages, topics, and project types.</p>
          {issue_cards}

          <h2 style="margin:28px 0 14px;font-size:22px;line-height:1.3;color:#0f172a;">Recommended first steps</h2>
          <ol style="margin:0 0 20px 22px;padding:0;color:#23364d;font-size:15px;line-height:1.9;">
            <li><a href="https://github.com/superplanehq/superplane" style="color:#155eef;text-decoration:none;">Explore the repository</a></li>
            <li><a href="https://github.com/superplanehq/superplane/blob/main/CONTRIBUTING.md" style="color:#155eef;text-decoration:none;">Read the contribution guide</a></li>
            <li>Open the best-matched issue above and read its latest discussion</li>
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
    def _issue_cards(scrape_result: GitHubScrapeResult) -> str:
        if not scrape_result.candidate_issues:
            return """
            <div style="margin:0 0 16px;padding:20px;border-radius:18px;background:#fff7ed;border:1px solid #fed7aa;color:#7c2d12;font-size:15px;line-height:1.7;">
              We could not load open issues during this run. Browse the <a href="https://github.com/superplanehq/superplane/issues" style="color:#9a3412;">live issue tracker</a> before choosing work.
            </div>
            """

        cards = []
        for index, issue in enumerate(scrape_result.candidate_issues[:3], start=1):
            number = f"#{issue.number} " if issue.number else ""
            labels = "".join(
                f'<span style="display:inline-block;margin:0 6px 6px 0;padding:4px 8px;border-radius:6px;background:#eef2ff;color:#3730a3;font-size:12px;">{escape(label)}</span>'
                for label in issue.labels[:4]
            )
            reasons = "".join(f"<li>{escape(reason)}</li>" for reason in issue.fit_reasons[:3])
            cards.append(
                f"""
                <div style="margin:0 0 14px;padding:20px;border-radius:18px;background:#ffffff;border:1px solid #dce6f2;">
                  <div style="margin-bottom:7px;font-size:12px;font-weight:700;text-transform:uppercase;color:#155eef;">Match {index} · Fit score {issue.fit_score}/100</div>
                  <a href="{escape(issue.html_url, quote=True)}" style="display:block;margin-bottom:10px;color:#0f172a;text-decoration:none;font-size:17px;line-height:1.45;font-weight:700;">{escape(number + issue.title)}</a>
                  {f'<div style="margin-bottom:8px;">{labels}</div>' if labels else ''}
                  <div style="margin:0 0 4px;color:#334155;font-size:13px;font-weight:700;">Why this fits you</div>
                  <ul style="margin:0;padding-left:20px;color:#475569;font-size:14px;line-height:1.7;">{reasons}</ul>
                </div>
                """
            )
        return "".join(cards)

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
