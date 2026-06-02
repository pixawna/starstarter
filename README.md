# StarStarter Demo

Star this repo to get a personalized contributor starter path.

This project now includes a simple FastAPI webhook service that:

- accepts the Superplane GitHub webhook payload for `star` events
- extracts the GitHub username from `data.body.sender.login`
- fetches the user's public GitHub profile, public email, and repositories
- fetches open issues from the starred repository
- uses OpenRouter to generate a personalized onboarding email

## Run locally

1. Create a virtual environment and install dependencies.
2. Copy `.env.example` to `.env` and fill in your keys.
3. Start the API:

```bash
uvicorn app.main:app --reload
```

The health endpoint is available at `GET /health`.

## Single ngrok setup

If you want GitHub to reach both Superplane and this FastAPI app through a single public URL, run the included gateway:

1. Run Superplane locally on `http://127.0.0.1:3000`
2. Run this FastAPI app on `http://127.0.0.1:8011`
3. Run the gateway on `http://127.0.0.1:8080`

```bash
uvicorn gateway:app --host 127.0.0.1 --port 8080
```

4. Expose only the gateway with ngrok:

```bash
ngrok http 8080
```

Then use the single public ngrok URL like this:

- GitHub `Payload URL`: `https://<gateway-ngrok-url>/api/v1/webhooks/<superplane-webhook-id>`
- Superplane HTTP node URL: `https://<gateway-ngrok-url>/webhooks/github/star`

The gateway forwards:

- `/api/v1/*` and the rest of the UI to Superplane on port `3000`
- `/webhooks/*` to this FastAPI app on port `8011`

## Webhook endpoint

Send the Superplane payload to:

```text
POST /webhooks/github/star
```

Expected payload shape:

```json
{
  "data": {
    "body": {
      "repository": {
        "full_name": "ConnectBhawna/starstarter"
      },
      "sender": {
        "login": "ConnectBhawna"
      }
    }
  }
}
```

## Environment variables

- `GITHUB_TOKEN`: optional, but recommended for higher GitHub API rate limits
- `GITHUB_AUTH_USERNAME`: optional GitHub username used together with `GITHUB_TOKEN` by `github-email-scraper`
- `OPENROUTER_API_KEY`: required for LLM-generated emails
- `OPENROUTER_MODEL`: optional, defaults to `openai/gpt-4o-mini`
- `APP_NAME`: sent to OpenRouter as the app title
- `APP_URL`: sent to OpenRouter as the referer

If `OPENROUTER_API_KEY` is not set, the service returns a deterministic fallback email so the webhook flow still works.

## Email enrichment

The app first uses the public email returned by the GitHub API. If that is empty, it optionally tries `github-email-scraper` to search publicly visible events and commit metadata for an email associated with the GitHub username.

## Sending email from Superplane

If the Superplane SMTP component rejects dynamic recipient expressions, let Superplane call this backend to send email instead.

1. Build the email payload with the existing HTTP node.
2. Add another HTTP node:

```text
POST /send-email
```

3. Point it to:

```text
https://<gateway-or-fastapi-url>/send-email
```

4. Send JSON:

```json
{
  "email": "{{$['Build Email Payload'].data.body.email}}",
  "subject": "{{$['Build Email Payload'].data.body.subject}}",
  "body": "{{$['Build Email Payload'].data.body.body}}"
}
```

Required SMTP environment variables:

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM_EMAIL` optional, defaults to `SMTP_USERNAME`
- `SMTP_USE_TLS`
