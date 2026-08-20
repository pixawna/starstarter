from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone

from app.models import GitHubProfileAnalysis, GitHubRepository, GitHubUserProfile


_PROJECT_TYPE_KEYWORDS = {
    "frontend/ui": (
        "frontend",
        "react",
        "next",
        "vue",
        "angular",
        "tailwind",
        "css",
        "ui",
        "ux",
        "component",
        "dashboard",
    ),
    "backend/api": (
        "backend",
        "api",
        "server",
        "fastapi",
        "django",
        "flask",
        "express",
        "graphql",
        "database",
    ),
    "workflow automation": (
        "automation",
        "workflow",
        "pipeline",
        "ci",
        "cd",
        "github actions",
        "bot",
        "integration",
    ),
    "developer tooling": (
        "cli",
        "sdk",
        "tool",
        "library",
        "package",
        "plugin",
        "extension",
        "template",
    ),
    "data/ai": (
        "data",
        "analytics",
        "machine learning",
        "ml",
        "ai",
        "llm",
        "notebook",
        "visualization",
    ),
    "docs/community": (
        "docs",
        "documentation",
        "tutorial",
        "guide",
        "readme",
        "community",
        "open source",
    ),
    "mobile": (
        "android",
        "ios",
        "flutter",
        "react native",
        "mobile",
    ),
    "devops/cloud": (
        "docker",
        "kubernetes",
        "terraform",
        "aws",
        "gcp",
        "azure",
        "deployment",
        "observability",
    ),
}


_STOP_TOPICS = {
    "app",
    "project",
    "demo",
    "test",
    "website",
    "github",
    "code",
}


def analyze_github_profile(
    *,
    profile: GitHubUserProfile,
    repositories: list[GitHubRepository],
    pinned_repositories: list[GitHubRepository],
) -> GitHubProfileAnalysis:
    all_repositories = _dedupe_repositories([*pinned_repositories, *repositories])
    language_distribution = _language_distribution(all_repositories)
    top_topics = _top_topics(all_repositories)
    project_types = _project_types(profile, all_repositories)
    notable_repositories = _notable_repositories(all_repositories)
    evidence = _evidence(profile, all_repositories, top_topics, project_types)

    return GitHubProfileAnalysis(
        primary_languages=list(language_distribution.keys())[:4],
        language_distribution=language_distribution,
        top_topics=top_topics,
        project_types=project_types,
        profile_strengths=_profile_strengths(profile, all_repositories, language_distribution, top_topics, project_types),
        contribution_fit=_contribution_fit(language_distribution, top_topics, project_types),
        notable_repositories=notable_repositories,
        evidence=evidence,
        activity_summary=_activity_summary(repositories),
        data_quality=_data_quality(profile, all_repositories, evidence),
    )


def _dedupe_repositories(repositories: list[GitHubRepository]) -> list[GitHubRepository]:
    deduped: list[GitHubRepository] = []
    seen: set[str] = set()
    for repo in repositories:
        key = repo.full_name.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(repo)
    return deduped


def _language_distribution(repositories: list[GitHubRepository]) -> dict[str, int]:
    counts = Counter(repo.language for repo in repositories if repo.language)
    return dict(counts.most_common(8))


def _top_topics(repositories: list[GitHubRepository]) -> list[str]:
    counts: Counter[str] = Counter()
    for repo in repositories:
        for topic in repo.topics:
            normalized = topic.strip().lower()
            if normalized and normalized not in _STOP_TOPICS:
                counts[normalized] += 1
    return [topic for topic, _ in counts.most_common(8)]


def _project_types(profile: GitHubUserProfile, repositories: list[GitHubRepository]) -> list[str]:
    corpus = _profile_corpus(profile)
    for repo in repositories:
        corpus += " " + _repo_corpus(repo)

    matches = []
    for project_type, keywords in _PROJECT_TYPE_KEYWORDS.items():
        if any(keyword in corpus for keyword in keywords):
            matches.append(project_type)
    return matches[:5]


def _profile_corpus(profile: GitHubUserProfile) -> str:
    return " ".join(
        filter(
            None,
            [
                profile.bio,
                profile.profile_summary,
                profile.profile_readme,
                " ".join(profile.inferred_interests),
                " ".join(profile.personalization_clues),
            ],
        )
    ).lower()


def _repo_corpus(repo: GitHubRepository) -> str:
    return " ".join(
        filter(
            None,
            [
                repo.name,
                repo.description,
                repo.language,
                " ".join(repo.topics),
            ],
        )
    ).lower()


def _profile_strengths(
    profile: GitHubUserProfile,
    repositories: list[GitHubRepository],
    language_distribution: dict[str, int],
    top_topics: list[str],
    project_types: list[str],
) -> list[str]:
    strengths = []
    if language_distribution:
        languages = ", ".join(list(language_distribution.keys())[:3])
        strengths.append(f"Works across {languages}")
    if project_types:
        strengths.append(f"Public work points toward {', '.join(project_types[:2])}")
    if top_topics:
        strengths.append(f"Repos repeatedly mention {', '.join(top_topics[:3])}")
    if profile.profile_readme or profile.profile_summary:
        strengths.append("Maintains public profile context that can guide onboarding")

    original_repos = [repo for repo in repositories if not repo.is_fork]
    if len(original_repos) >= 3:
        strengths.append("Shows original project work across multiple repositories")
    if any(repo.homepage for repo in repositories):
        strengths.append("Links some public repositories to live demos or project pages")

    popular_repo = max(repositories, key=lambda repo: repo.stargazers_count + repo.forks_count, default=None)
    if popular_repo and popular_repo.stargazers_count + popular_repo.forks_count > 0:
        strengths.append(f"Has visible project traction via {popular_repo.full_name}")

    return _unique(strengths)[:5]


def _contribution_fit(
    language_distribution: dict[str, int],
    top_topics: list[str],
    project_types: list[str],
) -> list[str]:
    corpus = " ".join([*language_distribution.keys(), *top_topics, *project_types]).lower()
    fits = []

    if any(term in corpus for term in ("frontend", "ui", "react", "typescript", "javascript")):
        fits.append("Frontend workflow UI and contributor experience")
    if any(term in corpus for term in ("backend", "api", "python", "fastapi", "go", "ruby")):
        fits.append("Backend API behavior, integrations, and error handling")
    if any(term in corpus for term in ("automation", "workflow", "pipeline", "devops", "cloud")):
        fits.append("Workflow automation examples and CI/CD scenarios")
    if any(term in corpus for term in ("docs", "documentation", "community", "tutorial")):
        fits.append("Documentation, examples, and first-contributor guidance")
    if any(term in corpus for term in ("data", "ai", "llm", "analytics")):
        fits.append("Developer-facing observability, summaries, and insight features")

    if not fits:
        fits.append("Small onboarding, docs, or product-polish issues")
    return _unique(fits)[:5]


def _notable_repositories(repositories: list[GitHubRepository]) -> list[str]:
    ranked = sorted(
        repositories,
        key=lambda repo: (
            0 if repo.archived else 1,
            0 if repo.is_fork else 1,
            repo.stargazers_count + repo.forks_count,
            len(repo.description or ""),
            repo.updated_at or "",
        ),
        reverse=True,
    )
    return [repo.full_name for repo in ranked[:5]]


def _evidence(
    profile: GitHubUserProfile,
    repositories: list[GitHubRepository],
    top_topics: list[str],
    project_types: list[str],
) -> list[str]:
    evidence = []
    if profile.bio:
        evidence.append(f"Bio: {profile.bio[:120]}")
    if profile.profile_summary:
        evidence.append(f"Profile summary: {profile.profile_summary[:140]}")
    if top_topics:
        evidence.append(f"Common repo topics: {', '.join(top_topics[:5])}")
    if project_types:
        evidence.append(f"Detected project types: {', '.join(project_types[:4])}")

    for repo in repositories[:4]:
        if repo.description:
            evidence.append(f"{repo.full_name}: {repo.description[:120]}")
        elif repo.homepage:
            evidence.append(f"{repo.full_name}: links to {repo.homepage}")
    return _unique(evidence)[:8]


def _activity_summary(repositories: list[GitHubRepository]) -> str | None:
    dates = [_parse_github_datetime(repo.updated_at) for repo in repositories if repo.updated_at]
    dates = [date for date in dates if date is not None]
    if not dates:
        return None

    newest = max(dates)
    age_days = (datetime.now(timezone.utc) - newest).days
    if age_days <= 30:
        return "Recently active in public repositories within the last month"
    if age_days <= 180:
        return "Public repository activity appears active within the last six months"
    if age_days <= 365:
        return "Public repository activity appears active within the last year"
    return "Public repository activity appears older than one year"


def _parse_github_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _data_quality(
    profile: GitHubUserProfile,
    repositories: list[GitHubRepository],
    evidence: list[str],
) -> str:
    score = 0
    if profile.bio or profile.profile_summary or profile.profile_readme:
        score += 1
    if len(repositories) >= 3:
        score += 1
    if evidence:
        score += 1
    if any(repo.description for repo in repositories):
        score += 1

    if score >= 4:
        return "strong"
    if score >= 2:
        return "moderate"
    return "limited"


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    cleaned = []
    for value in values:
        normalized = re.sub(r"\s+", " ", value).strip()
        lowered = normalized.lower()
        if not normalized or lowered in seen:
            continue
        seen.add(lowered)
        cleaned.append(normalized)
    return cleaned
