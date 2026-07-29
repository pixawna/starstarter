from typing import Any

from pydantic import BaseModel, Field

# This module defines all the data models used across the application. These models represent the structured data for GitHub user profiles, repositories, issues, and the payloads for webhooks and email sending. By using Pydantic's BaseModel, we ensure that the data is validated and structured consistently throughout the application, making it easier to work with and reducing the likelihood of errors when processing data from GitHub or handling webhook events.

class GitHubUserProfile(BaseModel):
    login: str
    name: str | None = None
    bio: str | None = None
    company: str | None = None
    location: str | None = None
    blog: str | None = None
    email: str | None = None
    profile_readme: str | None = None
    profile_summary: str | None = None
    inferred_interests: list[str] = Field(default_factory=list)
    personalization_clues: list[str] = Field(default_factory=list)
    public_repos: int = 0
    followers: int = 0
    following: int = 0


class GitHubRepository(BaseModel):
    name: str
    full_name: str
    description: str | None = None
    html_url: str
    language: str | None = None
    stargazers_count: int = 0
    forks_count: int = 0
    topics: list[str] = Field(default_factory=list)
    updated_at: str | None = None


class RepositoryIssue(BaseModel):
    title: str
    html_url: str
    labels: list[str] = Field(default_factory=list)
    body: str | None = None


class GitHubScrapeResult(BaseModel):
    profile: GitHubUserProfile
    repositories: list[GitHubRepository]
    candidate_issues: list[RepositoryIssue]
    pinned_repositories: list[GitHubRepository] = Field(default_factory=list)


class SuperplaneWebhookEnvelope(BaseModel):
    data: dict[str, Any]
    timestamp: str | None = None
    type: str | None = None


class WebhookProcessingResponse(BaseModel):
    email: str | None = None
    subject: str | None = None
    body: str | None = None
    email_send_skipped: bool = False
    detail: str | None = None


class SendEmailRequest(BaseModel):
    email: str | None = None
    subject: str
    body: str


class SendEmailResponse(BaseModel):
    success: bool
    to: str | None = None
    subject: str
    skipped: bool = False
    detail: str | None = None
