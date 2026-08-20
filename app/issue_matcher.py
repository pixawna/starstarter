from __future__ import annotations

import re
from datetime import datetime, timezone

from app.models import GitHubProfileAnalysis, RepositoryIssue


_SKILL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "frontend/UI": (
        "frontend", "ui", "ux", "react", "typescript", "javascript", "css",
        "component", "dashboard", "web", "form", "button", "modal",
    ),
    "backend/API": (
        "backend", "api", "server", "golang", "grpc", "database", "sql",
        "endpoint", "webhook", "authentication", "authorization",
    ),
    "workflow automation": (
        "workflow", "automation", "pipeline", "job", "event", "trigger",
        "approval", "deployment", "integration", "ci", "cd",
    ),
    "DevOps/cloud": (
        "docker", "kubernetes", "helm", "terraform", "cloud", "deployment",
        "observability", "prometheus", "container", "infra", "runner",
    ),
    "documentation": (
        "docs", "documentation", "readme", "guide", "tutorial", "example",
        "onboarding", "contributor",
    ),
    "testing/quality": (
        "test", "testing", "e2e", "unit", "integration test", "bug", "fix",
        "error", "validation", "reliability",
    ),
    "developer tooling": (
        "cli", "sdk", "tool", "plugin", "extension", "command", "developer experience",
    ),
    "data/AI": (
        "data", "analytics", "ai", "llm", "metric", "insight", "visualization",
    ),
}

_LANGUAGE_SKILLS: dict[str, tuple[str, ...]] = {
    "typescript": ("frontend/UI", "developer tooling"),
    "javascript": ("frontend/UI", "developer tooling"),
    "css": ("frontend/UI",),
    "html": ("frontend/UI", "documentation"),
    "go": ("backend/API", "workflow automation", "DevOps/cloud"),
    "python": ("backend/API", "workflow automation", "data/AI"),
    "ruby": ("backend/API", "developer tooling"),
    "java": ("backend/API",),
    "kotlin": ("backend/API",),
    "shell": ("workflow automation", "DevOps/cloud"),
    "hcl": ("DevOps/cloud",),
}

_BEGINNER_LABELS = {"good first issue", "good-first-issue", "beginner", "easy"}
_HELP_LABELS = {"help wanted", "help-wanted", "contributions welcome"}
_SMALL_SCOPE_LABELS = {"papercut", "small", "small fix"}
_BLOCKED_LABELS = {"blocked", "stale", "duplicate", "wontfix", "needs info", "needs-info"}


def rank_issues_for_profile(
    issues: list[RepositoryIssue],
    analysis: GitHubProfileAnalysis,
    *,
    limit: int = 5,
) -> list[RepositoryIssue]:
    """Rank real repository issues against skills evidenced by the public profile."""
    profile_skills = _profile_skill_weights(analysis)
    ranked = [_score_issue(issue, profile_skills) for issue in issues]
    ranked.sort(
        key=lambda issue: (
            issue.fit_score,
            -issue.assignees_count,
            issue.updated_at or "",
            issue.number or 0,
        ),
        reverse=True,
    )
    return ranked[:limit]


def _profile_skill_weights(analysis: GitHubProfileAnalysis) -> dict[str, int]:
    weights: dict[str, int] = {}

    for index, language in enumerate(analysis.primary_languages):
        language_weight = max(2, 6 - index)
        for skill in _LANGUAGE_SKILLS.get(language.lower(), ()):
            weights[skill] = weights.get(skill, 0) + language_weight

    corpus = " ".join(
        [
            *analysis.top_topics,
            *analysis.project_types,
            *analysis.contribution_fit,
            *analysis.profile_strengths,
        ]
    ).lower()
    for skill, keywords in _SKILL_KEYWORDS.items():
        matches = sum(1 for keyword in keywords if _contains_term(corpus, keyword))
        if matches:
            weights[skill] = weights.get(skill, 0) + min(matches * 2, 8)

    return weights


def _score_issue(issue: RepositoryIssue, profile_skills: dict[str, int]) -> RepositoryIssue:
    labels = {label.strip().lower() for label in issue.labels}
    corpus = " ".join([issue.title, issue.body or "", *issue.labels]).lower()
    issue_skills = {
        skill
        for skill, keywords in _SKILL_KEYWORDS.items()
        if any(_contains_term(corpus, keyword) for keyword in keywords)
    }

    matched = sorted(
        issue_skills.intersection(profile_skills),
        key=lambda skill: profile_skills[skill],
        reverse=True,
    )
    score = min(sum(12 + min(profile_skills[skill], 8) for skill in matched), 65)
    reasons = [f"Matches your {skill} experience" for skill in matched[:2]]

    if labels.intersection(_BEGINNER_LABELS):
        score += 18
        reasons.append("Marked as a good first issue")
    if labels.intersection(_HELP_LABELS):
        score += 10
        reasons.append("Maintainers are asking for contributor help")
    if labels.intersection(_SMALL_SCOPE_LABELS):
        score += 8
        reasons.append("Likely to be a contained first contribution")
    if labels.intersection(_BLOCKED_LABELS):
        score -= 30
    if issue.assignees_count == 0:
        score += 5
        reasons.append("Currently unassigned")
    else:
        score -= min(issue.assignees_count * 4, 12)

    if _updated_within_days(issue.updated_at, 120):
        score += 7
        reasons.append("Recently active")
    if issue.comments >= 12:
        score -= 4

    if not matched and profile_skills:
        score = max(score - 5, 0)
    if not reasons:
        reasons.append("Open contribution opportunity in Superplane")

    return issue.model_copy(
        update={
            "fit_score": max(0, min(score, 100)),
            "fit_reasons": reasons[:3],
            "matched_skills": matched[:3],
        }
    )


def _contains_term(corpus: str, term: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", corpus) is not None


def _updated_within_days(value: str | None, days: int) -> bool:
    if not value:
        return False
    try:
        updated_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - updated_at).days <= days
