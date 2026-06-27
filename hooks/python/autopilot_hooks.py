# SPDX-License-Identifier: MIT
"""Drop-in Autopilot hooks for a Python app (stdlib only).

    from autopilot_hooks import file_issue, report_error, prefilled_issue_url

Feed the queue with `file_issue(...)`; wire `report_error(...)` into your global
exception handler. Both are best-effort and never raise into your app.
"""

from __future__ import annotations

import hashlib
import json
import os
import traceback
import urllib.parse
import urllib.request

GITHUB_REPO = os.environ.get("AUTOPILOT_REPO", "OWNER/REPO")
GITHUB_TOKEN = os.environ.get("AUTOPILOT_GITHUB_TOKEN", "")
REPORT_ERRORS = os.environ.get("AUTOPILOT_REPORT_ERRORS", "").lower() in ("1", "true", "yes")

_seen: set[str] = set()


def file_issue(title: str, body: str, labels: list[str],
               repo: str = "", token: str = "") -> bool:
    """Open a GitHub issue. Returns True on success. Best-effort."""
    repo = repo or GITHUB_REPO
    token = token or GITHUB_TOKEN
    if not token:
        return False
    payload = json.dumps({"title": title, "body": body, "labels": labels}).encode()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues", data=payload,
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            return resp.status == 201
    except Exception:
        return False


def prefilled_issue_url(title: str, body: str, labels: list[str], repo: str = "") -> str:
    """A GitHub 'new issue' URL the user submits themselves (no token shipped)."""
    repo = repo or GITHUB_REPO
    q = urllib.parse.urlencode({"title": title, "body": body, "labels": ",".join(labels)})
    return f"https://github.com/{repo}/issues/new?{q}"


def report_error(exc: BaseException) -> bool:
    """Self-healing: file a deduped auto-fix issue. Opt-in (AUTOPILOT_REPORT_ERRORS)."""
    if not REPORT_ERRORS:
        return False
    fp = _fingerprint(exc)
    if fp in _seen:
        return False
    _seen.add(fp)
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return file_issue(
        f"[auto] {type(exc).__name__}: {str(exc)[:80]}",
        f"Auto-reported unhandled error (`{fp}`).\n\n```\n{tb[:4000]}\n```",
        ["bug", "auto-fix", "needs-triage"])


def _fingerprint(exc: BaseException) -> str:
    frame = ""
    for fr in traceback.extract_tb(exc.__traceback__):
        frame = f"{os.path.basename(fr.filename)}:{fr.lineno}"
    return hashlib.sha1(f"{type(exc).__name__}|{frame}".encode()).hexdigest()[:12]
