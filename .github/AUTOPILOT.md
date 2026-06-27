# Autopilot · Pillar 2 — feature-request queue

In-app feedback and feature requests become a triage queue you control. Nothing
is built without your sign-off.

## How it flows

1. **Capture** — users click **Feedback** in the dashboard (or use the GitHub
   issue forms). Each submission becomes an issue labelled `feature` or `bug`.
   - Customer installs (no token): the widget opens a **pre-filled issue** for
     the user to post under their own account — no privileged token ships.
   - Owner/dev installs: set `TUNAAR_GITHUB_TOKEN` (env only) and the app files
     the issue automatically.
   - Every submission is also queued locally in `/config/feedback.json`.
2. **Triage** — the GitHub issues list *is* the queue. Review and apply one of:
   | Label | Meaning |
   |---|---|
   | `approved` | Sign off → eligible to build |
   | `declined` | Won't do |
   | `changes-requested` | Needs refinement before it can be approved |
3. **Build (gated)** — the `Autopilot — approved build gate` workflow fires
   **only** on `approved`, records sign-off, and is the single hook where the
   Pillar 1 implementation agent runs. It stays inert until you set
   `ANTHROPIC_API_KEY`, so approving never auto-writes code by surprise.

## One-time setup

- Create the labels: `feature`, `bug`, `approved`, `declined`,
  `changes-requested`.
- (Optional) Owner install: set `TUNAAR_GITHUB_TOKEN` to auto-file issues.
- (Optional) To enable Pillar 1 auto-build later: add `ANTHROPIC_API_KEY` and
  wire the build action into the marked step of the workflow.

## Reusing this in another product

The capture engine is a single self-contained file — `tunaar/feedback.py`
(stdlib + `requests`, no framework/product coupling). Copy it in, construct a
`FeedbackHub` with your app name + repo, and add a POST route. Copy this
`.github/` folder (workflow + issue forms) for the queue side. See the module
docstring for the full reuse recipe.
