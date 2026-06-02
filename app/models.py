from typing import Any

from pydantic import BaseModel, Field


class GitHubUserProfile(BaseModel):
    login: str
    name: str | None = None
    bio: str | None = None
    company: str | None = None
    location: str | None = None
    blog: str | None = None
    email: str | None = None
    profile_readme: str | None = None
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


class SuperplaneWebhookEnvelope(BaseModel):
    data: dict[str, Any]
    timestamp: str | None = None
    type: str | None = None


class WebhookProcessingResponse(BaseModel):
    email: str | None = None
    subject: str | None = None
    body: str | None = None


class SendEmailRequest(BaseModel):
    email: str
    subject: str
    body: str


class SendEmailResponse(BaseModel):
    success: bool
    to: str
    subject: str
