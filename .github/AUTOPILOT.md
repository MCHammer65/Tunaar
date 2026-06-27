# Autopilot — product operations for Tunaar

A hands-off operations pipeline running on **GitHub Issues + a fixed label
vocabulary**, with a human gate exactly where it matters (approving feature
work, reviewing risky fixes, sending forum posts).

## Pillars

| Pillar | What it does |
|---|---|
| **1 · Self-healing** | Nightly self-test + Dependabot (and an optional vendor-side runtime reporter) raise `auto-fix` issues → `autofix.yml` opens a fix PR with a regression test → you review + merge (never an auto-push). |
| **2 · Feature queue** | In-app Feedback + issue forms capture requests → you triage → `feature-queue.yml` builds **only** on `approved` (a PR you merge). |
| **3 · Marketing** | Tagging `vX.Y.Z` runs `release.yml`: drafts release notes + Reddit/HN/X/Mastodon/Discord posts (artifacts), and auto-posts to **owned** channels when their secrets are set. Forums stay drafts. |
| **4 · Reusable** | The capture engine (`tunaar/feedback.py`) and the generic `hooks/` are product-agnostic; copy them + this `.github/` folder into any product. |

## Files

```
.github/
  labels.yml                       triage label vocabulary (the "API")
  dependabot.yml                   dependency/action auto-fix PRs
  ISSUE_TEMPLATE/                  feature + bug capture forms
  workflows/labels-sync.yml        create/update labels (manual run)
  workflows/triage.yml             acknowledge new issues
  workflows/feature-queue.yml      approved → build PR; declined → close
  workflows/autofix.yml            auto-fix label → fix PR
  workflows/selftest.yml           nightly suite → auto-fix issue on break
  workflows/release.yml            tag → release notes + announcement drafts
scripts/gen_announcements.py       release → platform announcement drafts/posts
hooks/                             portable drop-in capture hooks (Python/JS/curl)
CHANGELOG.md                       Keep-a-Changelog; drives release notes
```

## Setup (one-time)

1. **Settings → Actions → General → Workflow permissions:** Read and write +
   "Allow GitHub Actions to create and approve pull requests".
2. **Secrets:** `ANTHROPIC_API_KEY` (build/fix agents). Optional:
   `ANNOUNCE_DISCORD_WEBHOOK`, `ANNOUNCE_MASTODON_INSTANCE` + `ANNOUNCE_MASTODON_TOKEN`.
3. **Actions → Sync labels → Run workflow** once to create the label vocabulary.
4. (Owner install only) set `TUNAAR_GITHUB_TOKEN` so the in-app widget files
   issues automatically; customer installs use a tokenless pre-filled issue link.

## Daily use

- Requests land with `needs-triage`. Apply **`approved`**, **`declined`**, or
  **`changes-requested`**.
- `approved` → agent opens a PR. `auto-fix` (from a bug/self-test) → fix PR.
- You review + merge. Tag `vX.Y.Z` to ship + announce.

## Guardrails (by design)

- **Approve-before-build:** nothing is implemented without your `approved` label;
  only users with write access can apply labels.
- **No direct pushes:** agents open PRs you merge.
- **Safe-class only for auto-fix:** lint, dep bumps, and fixes whose new test
  proves them; everything else waits for review.
- **Never bot-post forums:** Reddit/HN stay drafts for a human to send.
- **Agents are inert without `ANTHROPIC_API_KEY`:** the workflows exist but do
  nothing until you add the secret.

## Reuse in another product

Copy `tunaar/feedback.py` (or a `hooks/` variant), this `.github/` folder, and
`scripts/gen_announcements.py` into the target repo, then follow Setup above. The
whole pipeline is just "file a labelled issue", so anything that can POST to the
GitHub Issues API inherits it.
