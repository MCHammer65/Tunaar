# App-side hooks — the only per-stack code

The Autopilot runs on GitHub Issues + labels, so your app only has to **file an
issue** to feed it. Two hooks:

1. **Feedback / feature capture** — when a user submits feedback, open an issue
   labelled by category: `feature` + `needs-triage`, `bug` + `needs-triage`, or
   `feedback` + `needs-triage`.
2. **Error reporting (optional self-healing)** — on an unhandled error, open a
   **deduplicated** issue labelled `bug`,`auto-fix`,`needs-triage`.
   ⚠️ Make this **opt-in / vendor-side only** so customer installs don't file to
   your tracker. Dedup by a fingerprint (error type + top app frame) so one bug
   files once.

## The universal contract
```
POST https://api.github.com/repos/<owner>/<repo>/issues
Authorization: Bearer <token>          # a fine-grained PAT with issues:write
Accept: application/vnd.github+json
{ "title": "...", "body": "...", "labels": ["feature","needs-triage"] }
```
That's the entire integration. Anything that can make that call inherits the
whole pipeline. Examples below: `python/`, `examples/file_issue.js`,
`examples/file_issue.sh`.

> No token to ship to customers? Instead build a **prefilled issue URL** and open
> it in the browser so the user submits with their own account — no secret in the
> app: `https://github.com/<owner>/<repo>/issues/new?title=…&body=…&labels=feature`
