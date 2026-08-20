# StarStarter: Superplane + GitHub setup guide

This guide explains the first StarStarter steps in beginner-friendly language:

```text
User stars the Superplane repo
↓
Superplane workflow is triggered
↓
StarStarter checks the GitHub profile
```

The important idea: **a GitHub star is a GitHub webhook event**. Superplane's GitHub component currently documents triggers for branches, issues, pull requests, pushes, releases, tags, workflow runs, and comments, but not a built-in star trigger. So the simplest working setup is:

1. Create a **Superplane Webhook** trigger.
2. Tell **GitHub** to send only the **Star** event to that webhook.
3. Add Superplane HTTP steps that call the GitHub API to read the stargazer's profile and repositories.

## What you need first

- Superplane open locally, for example: `http://localhost:3003`.
- A GitHub repository you control, for example `superplanehq/superplane` or your fork.
- Admin access to that GitHub repository so you can create a webhook.
- A way for GitHub to reach your local Superplane. GitHub cannot call `localhost` on your laptop directly, so for local testing use a tunnel such as `ngrok http 3003` or `cloudflared tunnel --url http://localhost:3003`.
- Optional but recommended: a GitHub token stored as a Superplane secret. Public profile and public repository calls can work without a token, but a token gives better rate limits and more reliable API access.

## Step 1: create the Superplane webhook trigger

1. Open Superplane at `http://localhost:3003`.
2. Open or create a canvas named `StarStarter`.
3. Add a trigger node: **Core → Webhook**.
4. Name it `GitHub Star Received`.
5. Choose authentication:
   - For a quick local demo: **Header Token** is easiest.
   - For production: use **Signature (HMAC)** so GitHub signs each request and Superplane verifies it.
6. Copy the generated webhook URL.

Beginner translation: this node is StarStarter's front door. Whenever GitHub sends a star message to this URL, Superplane starts the workflow.

## Step 2: make the local webhook reachable from GitHub

If the generated webhook URL starts with `http://localhost:3003`, GitHub will not be able to reach it. Start a tunnel and replace only the host part of the URL.

Example:

```bash
ngrok http 3003
```

If Superplane gives this local URL:

```text
http://localhost:3003/webhooks/abc123
```

and ngrok gives this public URL:

```text
https://happy-demo.ngrok-free.app
```

then give GitHub this URL:

```text
https://happy-demo.ngrok-free.app/webhooks/abc123
```

Keep the tunnel running while you test stars.

## Step 3: connect GitHub stars to the Superplane webhook

1. Go to your GitHub repo.
2. Open **Settings → Webhooks → Add webhook**.
3. Paste the public Superplane webhook URL.
4. Set **Content type** to `application/json`.
5. Add your webhook secret or header token, matching the authentication method you chose in Superplane.
6. Under **Which events would you like to trigger this webhook?**, choose **Let me select individual events**.
7. Select **Stars** only.
8. Save the webhook.

GitHub will send a test `ping` first. After that, when someone stars the repository, GitHub sends a `star` payload with `action: created`, a `sender` user, and the repository details.

## Step 4: add a safety filter for real star-created events

Add a Superplane **Core → Filter** node after `GitHub Star Received`.

Name it `Only New Stars` and use this expression:

```text
root().data.body.action == "created" && root().data.headers["X-GitHub-Event"][0] == "star"
```

Why this matters: GitHub can also send a star deletion event when somebody unstars. This filter keeps StarStarter focused only on new stars.

If your local run shows header keys in a different case, use the exact header key shown in the latest run payload.

## Step 5: check the stargazer's GitHub profile

Add a Superplane **Core → HTTP Request** node after `Only New Stars`.

Name it `Get GitHub Profile` and configure it like this:

| Field | Value |
| --- | --- |
| Method | `GET` |
| URL | `https://api.github.com/users/{{ root().data.body.sender.login }}` |
| Header `Accept` | `application/vnd.github+json` |
| Header `X-GitHub-Api-Version` | `2022-11-28` |
| Authorization | Optional bearer token from a Superplane secret |

This reads public profile information for the user who starred the repo, using `sender.login` from the GitHub webhook payload.

Useful profile fields for later StarStarter logic:

- `login`: GitHub username.
- `name`: display name, if public.
- `bio`: what the user says about themself.
- `blog`: website, if public.
- `company`: company, if public.
- `location`: location, if public.
- `public_repos`: public repository count.
- `followers`: follower count.
- `created_at`: account age.

## Step 6: fetch the stargazer's public repositories

Add another Superplane **Core → HTTP Request** node after `Get GitHub Profile`.

Name it `Get Public Repos` and configure it like this:

| Field | Value |
| --- | --- |
| Method | `GET` |
| URL | `https://api.github.com/users/{{ root().data.body.sender.login }}/repos` |
| Query `type` | `owner` |
| Query `sort` | `updated` |
| Query `direction` | `desc` |
| Query `per_page` | `20` |
| Header `Accept` | `application/vnd.github+json` |
| Header `X-GitHub-Api-Version` | `2022-11-28` |
| Authorization | Optional bearer token from a Superplane secret |

This gives StarStarter a quick view of what the person builds or works with.

Good fields to inspect later:

- `name` and `full_name`: repository names.
- `description`: project summary.
- `language`: main programming language.
- `topics`: project tags.
- `stargazers_count`: popularity signal.
- `fork`: whether it is their own project or a fork.
- `updated_at`: how recently they worked on it.

## Step 7: add a debug display so non-devs can confirm it worked

Add a Superplane **Core → Display** node after `Get Public Repos`.

Name it `Show StarStarter Summary` and display a message like:

```text
New star from {{ root().data.body.sender.login }}.
Profile checked. Public repos fetched. Next step: analyze interests and suggest a contribution path.
```

At this point you have completed the first three requested workflow steps.

## Step 8: test without waiting for a real stranger

Use one of these simple tests:

1. Ask a friend to star the repo.
2. Star the repo from a second GitHub account.
3. In GitHub webhook settings, open the latest delivery and use **Redeliver** after your Superplane tunnel is running.

In Superplane, open the latest run for `GitHub Star Received` and confirm these values exist:

```text
root().data.body.action
root().data.body.sender.login
root().data.body.repository.full_name
```

Expected values for a new star:

```text
action = created
sender.login = the GitHub username that starred the repo
repository.full_name = the repo that was starred
```

## Recommended first canvas layout

```text
GitHub Star Received
  ↓
Only New Stars
  ↓
Get GitHub Profile
  ↓
Get Public Repos
  ↓
Show StarStarter Summary
```

## What comes next after these first steps

After the profile and repositories are available, the next StarStarter pieces can be added as separate nodes:

1. **Understand interests/skills**: inspect repository languages, topics, descriptions, and recent activity.
2. **Suggest contribution path**: map the user's signals to beginner-friendly issues, docs, examples, or tutorials.
3. **Send onboarding**: email is tricky because GitHub often hides public email addresses; safer first options are a generated starter page, GitHub issue comment for opted-in users, or a community page link.
4. **Community page**: create a page with tutorials, contribution guides, and help channels.

## Common mistakes

- Do not paste a `localhost` webhook URL into GitHub unless you are only doing manual local curl tests. GitHub needs a public HTTPS URL.
- Do not select every GitHub webhook event. Select **Stars** only, or your workflow will run for unrelated activity.
- Do not assume GitHub exposes email addresses. Most users keep emails private.
- Do not skip authentication for production webhooks.
- Do not process `action: deleted` unless you intentionally want to react to unstars.
