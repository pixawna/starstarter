from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.analyzer import OnboardingEmailGenerator
from app.config import Settings
from app.issue_matcher import rank_issues_for_profile
from app.models import (
    GitHubProfileAnalysis,
    GitHubScrapeResult,
    GitHubUserProfile,
    RepositoryIssue,
)


class IssueMatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.issues = [
            RepositoryIssue(
                number=101,
                title="Improve React workflow form validation",
                html_url="https://github.com/superplanehq/superplane/issues/101",
                labels=["area: web", "good first issue"],
                body="Update the TypeScript component and add UI validation tests.",
                updated_at=datetime.now(timezone.utc).isoformat(),
            ),
            RepositoryIssue(
                number=202,
                title="Add retry behavior to Go webhook worker",
                html_url="https://github.com/superplanehq/superplane/issues/202",
                labels=["area: backend"],
                body="Improve API reliability for workflow event delivery.",
                updated_at=datetime.now(timezone.utc).isoformat(),
            ),
            RepositoryIssue(
                number=303,
                title="Document local setup",
                html_url="https://github.com/superplanehq/superplane/issues/303",
                labels=["documentation", "help wanted"],
                body="Add a contributor guide and examples.",
                assignees_count=1,
            ),
        ]

    def test_frontend_profile_prefers_frontend_issue(self) -> None:
        analysis = GitHubProfileAnalysis(
            primary_languages=["TypeScript", "JavaScript"],
            project_types=["frontend/ui"],
            contribution_fit=["Frontend workflow UI and contributor experience"],
        )

        ranked = rank_issues_for_profile(self.issues, analysis)

        self.assertEqual(ranked[0].number, 101)
        self.assertIn("frontend/UI", ranked[0].matched_skills)
        self.assertGreater(ranked[0].fit_score, ranked[1].fit_score)

    def test_backend_profile_prefers_backend_issue(self) -> None:
        analysis = GitHubProfileAnalysis(
            primary_languages=["Go"],
            project_types=["backend/api", "workflow automation"],
            contribution_fit=["Backend API behavior, integrations, and error handling"],
        )

        ranked = rank_issues_for_profile(self.issues, analysis)

        self.assertEqual(ranked[0].number, 202)
        self.assertIn("backend/API", ranked[0].matched_skills)

    def test_blocked_issue_is_deprioritized(self) -> None:
        blocked = RepositoryIssue(
            number=404,
            title="Improve React workflow form",
            html_url="https://github.com/superplanehq/superplane/issues/404",
            labels=["area: web", "blocked"],
            body="Update the TypeScript UI component.",
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        analysis = GitHubProfileAnalysis(
            primary_languages=["TypeScript"],
            project_types=["frontend/ui"],
        )

        ranked = rank_issues_for_profile([blocked, *self.issues], analysis)

        self.assertNotEqual(ranked[0].number, 404)

    def test_email_contains_only_ranked_real_issue_links(self) -> None:
        analysis = GitHubProfileAnalysis(
            primary_languages=["TypeScript"],
            project_types=["frontend/ui"],
        )
        ranked = rank_issues_for_profile(self.issues, analysis)
        scrape_result = GitHubScrapeResult(
            profile=GitHubUserProfile(login="octocat", public_repos=3),
            repositories=[],
            candidate_issues=ranked,
            analysis=analysis,
        )
        generator = OnboardingEmailGenerator(Settings())

        email = generator.generate_fallback_email(scrape_result)

        self.assertIn("Superplane issues matched to your skills", email)
        self.assertIn("issues/101", email)
        self.assertIn("Why this fits you", email)
        self.assertNotIn("Improve dashboard components", email)


if __name__ == "__main__":
    unittest.main()
