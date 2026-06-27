# Copyright (C) 2026 Muneris Management Ltd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Autopilot · Pillar 2 — feedback / feature-request capture queue.

A self-contained, product-agnostic module for capturing in-app feedback and
feature requests and turning them into a triage queue. It does three things,
in order of preference, and never loses a submission:

1. **Local queue** (always): every submission is appended to a JSON file so the
   owner has an on-box audit trail / queue even with no GitHub configured.
2. **GitHub issue via API** (when a token is configured — owner/dev installs):
   files a labelled issue automatically (``feature`` / ``bug`` / ``feedback``).
3. **Pre-filled issue URL** (tokenless — customer installs): returns a
   ``github.com/<repo>/issues/new?...`` link the UI opens, so the user files it
   under their own GitHub account. No privileged token ever ships to customers.

The triage queue itself is just GitHub issues + labels: the owner applies
``approved`` / ``declined`` / ``changes-requested``, and only ``approved`` items
trigger a build (see the approve-before-build workflow). Nothing is built
without owner sign-off.

----------------------------------------------------------------------------
Reuse in another product
----------------------------------------------------------------------------
This file has **no framework or product imports** — only the stdlib and
``requests``. To reuse it:

1. Copy ``feedback.py`` into your project.
2. Construct one hub::

       hub = FeedbackHub(
           app_name="MyApp", version="1.2.3",
           store_path="/config/feedback.json",
           github_repo="me/myapp",            # public repo for issue links
           github_token=os.environ.get("GH_TOKEN", ""),  # owner-only; optional
       )

3. On submit:  ``result = hub.submit(kind, title, message, email)``
   - ``result.issue_url``  → filed automatically (token present), or
   - ``hub.issue_url(result)`` → a pre-filled link your UI opens (no token).
4. To read the queue:  ``hub.list()``.

No other wiring is required; HTTP routing/UI is the host app's job.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
from dataclasses import asdict, dataclass

import requests

KINDS = ("feature", "bug", "other")
DEFAULT_LABELS = {"feature": ["feature"], "bug": ["bug"], "other": ["feedback"]}


def _norm_kind(kind: str) -> str:
    return kind if kind in KINDS else "other"


@dataclass
class Feedback:
    """One captured submission."""

    id: str
    kind: str
    title: str
    message: str = ""
    email: str = ""
    app: str = ""
    version: str = ""
    created_at: float = 0.0
    issue_url: str = ""  # set when filed to GitHub via the API


class GitHubIssues:
    """Minimal GitHub Issues client (create only) — stdlib-friendly, no SDK."""

    def __init__(self, repo: str, token: str, *, api: str = "https://api.github.com",
                 timeout: int = 10) -> None:
        self.repo = repo
        self.token = token
        self.api = api
        self.timeout = timeout

    def create(self, title: str, body: str, labels: list[str]) -> dict:
        resp = requests.post(
            f"{self.api}/repos/{self.repo}/issues",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"title": title, "body": body, "labels": labels},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()


class FeedbackStore:
    """Thread-safe, append-only JSON queue (atomic writes)."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()

    def _read(self) -> list[dict]:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def add(self, fb: Feedback) -> None:
        with self._lock:
            items = self._read()
            items.append(asdict(fb))
            directory = os.path.dirname(os.path.abspath(self.path)) or "."
            os.makedirs(directory, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(items, fh, indent=2)
            os.replace(tmp, self.path)

    def list(self) -> list[dict]:
        with self._lock:
            return self._read()


class FeedbackHub:
    """Capture feedback into a local queue and (when able) GitHub issues."""

    def __init__(
        self,
        *,
        app_name: str = "",
        version: str = "",
        store_path: str = "feedback.json",
        github_repo: str = "",
        github_token: str = "",
        labels: dict | None = None,
    ) -> None:
        self.app_name = app_name
        self.version = version
        self.repo = (github_repo or "").strip()
        self.labels = labels or dict(DEFAULT_LABELS)
        self.store = FeedbackStore(store_path)
        self._gh = (
            GitHubIssues(self.repo, github_token)
            if (self.repo and github_token) else None
        )

    @property
    def github_enabled(self) -> bool:
        """True when issues are filed automatically via the API (token set)."""
        return self._gh is not None

    @property
    def link_enabled(self) -> bool:
        """True when a pre-filled issue URL can be offered (public repo set)."""
        return bool(self.repo)

    def submit(self, kind: str, title: str, message: str = "", email: str = "",
               *, now: float | None = None) -> Feedback:
        """Validate, store, and (if a token is set) file an issue. Never raises
        on a GitHub error — the local queue is the source of truth."""
        title = (title or "").strip()
        if not title:
            raise ValueError("title is required")
        kind = _norm_kind(kind)
        now = time.time() if now is None else now
        fb = Feedback(
            id=format(int(now * 1000), "x"),
            kind=kind,
            title=title[:140],
            message=(message or "").strip()[:4000],
            email=(email or "").strip()[:200],
            app=self.app_name,
            version=self.version,
            created_at=now,
        )
        if self._gh is not None:
            try:
                issue = self._gh.create(
                    self._issue_title(fb), self._issue_body(fb),
                    self.labels.get(kind, DEFAULT_LABELS["other"]),
                )
                fb.issue_url = issue.get("html_url", "")
            except Exception:  # noqa: BLE001 — never lose feedback on API failure
                pass
        self.store.add(fb)
        return fb

    def issue_url(self, fb: Feedback) -> str:
        """A pre-filled ``issues/new`` URL for tokenless (customer) submission."""
        if not self.repo:
            return ""
        query = urllib.parse.urlencode({
            "title": self._issue_title(fb),
            "body": self._issue_body(fb),
            "labels": ",".join(self.labels.get(fb.kind, DEFAULT_LABELS["other"])),
        })
        return f"https://github.com/{self.repo}/issues/new?{query}"

    def list(self) -> list[dict]:
        return self.store.list()

    # -- formatting -------------------------------------------------------

    def _issue_title(self, fb: Feedback) -> str:
        return f"[{fb.kind}] {fb.title}"

    def _issue_body(self, fb: Feedback) -> str:
        lines = [fb.message or "_(no description provided)_", "", "---",
                 f"- **Type:** {fb.kind}",
                 f"- **From app:** {self.app_name} {self.version}".rstrip()]
        if fb.email:
            lines.append(f"- **Contact:** {fb.email}")
        return "\n".join(lines)
