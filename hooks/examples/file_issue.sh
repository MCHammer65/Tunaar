#!/usr/bin/env bash
# File an Autopilot issue from any shell. Needs a PAT with issues:write.
set -euo pipefail
REPO="${AUTOPILOT_REPO:-OWNER/REPO}"
curl -fsS -X POST "https://api.github.com/repos/${REPO}/issues" \
  -H "Authorization: Bearer ${AUTOPILOT_GITHUB_TOKEN:?set a token}" \
  -H "Accept: application/vnd.github+json" \
  -d "$(jq -n --arg t "$1" --arg b "${2:-}" \
        '{title:$t, body:$b, labels:["feature","needs-triage"]}')"
