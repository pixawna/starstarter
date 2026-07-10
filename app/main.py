from __future__ import annotations

import json
import smtplib
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

from app.analyzer import OnboardingEmailGenerator
from app.config import get_settings
from app.github import GitHubClient
from app.mailer import Mailer
from app.models import (
    GitHubScrapeResult,
    GitHubUserProfile,
    SendEmailRequest,
    SendEmailResponse,
    WebhookProcessingResponse,
)

app = FastAPI(title="StarStarter Webhook Service")

# It exposes the FastAPI endpoints that SuperPlane communicates with. Whenever SuperPlane forwards a GitHub event, this is where the backend receives the request and starts the processing pipeline.

def _try_parse_json_string(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    if not ((text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]"))):
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _normalize_payload(payload: Any) -> dict[str, Any]:
    payload = _try_parse_json_string(payload)

    if not isinstance(payload, dict):
        return {}

    if "sender" in payload or "repository" in payload:
        return payload

    for key in ("json", "body", "payload", "data"):
        candidate = payload.get(key)
        parsed_candidate = _try_parse_json_string(candidate)
        if isinstance(parsed_candidate, dict):
            normalized_candidate = _normalize_payload(parsed_candidate)
            if normalized_candidate:
                return normalized_candidate

    return payload


def _coerce_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    coerced: dict[str, Any] = {}
    for key, value in mapping.items():
        coerced[key] = _try_parse_json_string(value)
    return coerced


def _extract_github_body(payload: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_payload(payload)
    data = payload.get("data")
    if isinstance(data, dict):
        body = _try_parse_json_string(data.get("body"))
        if isinstance(body, dict):
            return body
    return payload


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


async def _handle_star_webhook(payload: dict[str, Any]) -> WebhookProcessingResponse:
    settings = get_settings()
    body = _extract_github_body(payload)

    try:
        action = body.get("action")
        github_username = body.get("github_username") or body["sender"]["login"]
        repository_full_name = body.get("repository_full_name") or body["repository"]["full_name"]
    except KeyError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "Missing expected webhook field. Send either "
                "`github_username` + `repository_full_name` or "
                "nested `sender.login` + `repository.full_name`."
            ),
        ) from exc

    if action and action != "created":
        return WebhookProcessingResponse(
            email=None,
            subject=None,
            body=None,
        )

    github_client = GitHubClient(settings)
    email_generator = OnboardingEmailGenerator(settings)

    try:
        scrape_result = await github_client.scrape_user(github_username, repository_full_name)
        generated_email = await email_generator.generate_email(scrape_result, repository_full_name)
    except httpx.HTTPStatusError as exc:
        print("Upstream API error while processing webhook:", exc.response.text)
        scrape_result = GitHubScrapeResult(
            profile=GitHubUserProfile(login=github_username),
            repositories=[],
            candidate_issues=[],
        )
        generated_email = email_generator._fallback_email(scrape_result)
    except httpx.HTTPError as exc:
        print("Network error while processing webhook:", repr(exc))
        scrape_result = GitHubScrapeResult(
            profile=GitHubUserProfile(login=github_username),
            repositories=[],
            candidate_issues=[],
        )
        generated_email = email_generator._fallback_email(scrape_result)
    except Exception as exc:
        print("Unexpected webhook processing error:", repr(exc))
        scrape_result = GitHubScrapeResult(
            profile=GitHubUserProfile(login=github_username),
            repositories=[],
            candidate_issues=[],
        )
        generated_email = email_generator._fallback_email(scrape_result)

    email = scrape_result.profile.email
    subject = email_generator.generate_subject(github_username)
    body_content = generated_email

    return WebhookProcessingResponse(
        email=email,
        subject=subject,
        body=body_content,
    )


async def _read_request_payload(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    raw_body = (await request.body()).decode("utf-8", errors="ignore")
    try:
        if "application/json" in content_type:
            payload = json.loads(raw_body) if raw_body else {}
        elif "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
            form = await request.form()
            payload = _coerce_mapping(dict(form))
        else:
            payload = json.loads(raw_body) if raw_body else {}
    except Exception:
        payload = {"raw_body": raw_body}
    normalized = _normalize_payload(payload)
    if normalized:
        return normalized
    print("Webhook parse failure.")
    print("Content-Type:", content_type)
    print("Raw body received:", raw_body)
    raise HTTPException(
        status_code=400,
        detail=(
            "Could not parse webhook payload. Send JSON containing at least "
            "`sender.login` and `repository.full_name`. Raw body was logged "
            "to the FastAPI console."
        ),
    )


@app.post("/webhooks/github/star", response_model=WebhookProcessingResponse)
async def process_star_webhook(request: Request) -> WebhookProcessingResponse:
    payload = await _read_request_payload(request)
    result = await _handle_star_webhook(payload)
    accept = request.headers.get("accept", "")
    if "text/plain" in accept and result.body:
        return PlainTextResponse(result.body)
    return result


@app.post("/api/v1/webhooks/{webhook_id}", response_model=WebhookProcessingResponse)
async def process_superplane_style_webhook(webhook_id: str, request: Request) -> WebhookProcessingResponse:
    del webhook_id
    payload = await _read_request_payload(request)
    result = await _handle_star_webhook(payload)
    accept = request.headers.get("accept", "")
    if "text/plain" in accept and result.body:
        return PlainTextResponse(result.body)
    return result


@app.post("/send-email", response_model=SendEmailResponse)
async def send_email(payload: SendEmailRequest) -> SendEmailResponse:
    recipient = payload.email.strip() if payload.email else None
    if not recipient or recipient.lower() in {"null", "none", "undefined"}:
        return SendEmailResponse(
            success=False,
            to=None,
            subject=payload.subject,
            skipped=True,
            detail="No public recipient email was found for this GitHub user.",
        )

    settings = get_settings()
    mailer = Mailer(settings)

    try:
        mailer.send(to_email=recipient, subject=payload.subject, body=payload.body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except smtplib.SMTPException as exc:
        print("SMTP send failed:", repr(exc))
        raise HTTPException(status_code=502, detail=f"SMTP send failed: {exc}") from exc
    except OSError as exc:
        print("SMTP network failure:", repr(exc))
        raise HTTPException(status_code=502, detail=f"SMTP connection failed: {exc}") from exc

    return SendEmailResponse(success=True, to=recipient, subject=payload.subject)
