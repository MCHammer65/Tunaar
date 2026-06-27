# Copyright (C) 2026 Muneris Management Ltd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the portable Autopilot feedback module."""

import json

import pytest

from tunaar import feedback


def test_submit_stores_locally(tmp_path):
    hub = feedback.FeedbackHub(app_name="T", version="1.0",
                               store_path=str(tmp_path / "fb.json"))
    fb = hub.submit("feature", "Add dark mode", "please", "a@b.com", now=1.0)
    assert fb.kind == "feature" and fb.title == "Add dark mode"
    assert not hub.github_enabled and not hub.link_enabled
    stored = hub.list()
    assert len(stored) == 1 and stored[0]["email"] == "a@b.com"
    # Persisted as a JSON array on disk.
    with open(tmp_path / "fb.json") as fh:
        assert isinstance(json.load(fh), list)


def test_submit_requires_title(tmp_path):
    hub = feedback.FeedbackHub(store_path=str(tmp_path / "fb.json"))
    with pytest.raises(ValueError):
        hub.submit("bug", "   ")


def test_unknown_kind_normalised(tmp_path):
    hub = feedback.FeedbackHub(store_path=str(tmp_path / "fb.json"))
    assert hub.submit("nonsense", "x").kind == "other"


def test_issue_url_prefilled_when_repo_set(tmp_path):
    hub = feedback.FeedbackHub(app_name="T", store_path=str(tmp_path / "fb.json"),
                               github_repo="me/app")
    assert hub.link_enabled and not hub.github_enabled
    fb = hub.submit("bug", "Crash on start", "stacktrace", now=2.0)
    url = hub.issue_url(fb)
    assert url.startswith("https://github.com/me/app/issues/new?")
    assert "Crash+on+start" in url and "labels=bug" in url


def test_github_api_used_when_token_set(tmp_path, monkeypatch):
    created = {}

    class FakeResp:
        def raise_for_status(self):  # noqa: D401
            pass

        def json(self):
            return {"html_url": "https://github.com/me/app/issues/42"}

    def fake_post(url, **kwargs):
        created["url"] = url
        created["json"] = kwargs.get("json")
        return FakeResp()

    monkeypatch.setattr(feedback.requests, "post", fake_post)
    hub = feedback.FeedbackHub(app_name="T", store_path=str(tmp_path / "fb.json"),
                               github_repo="me/app", github_token="tok")
    assert hub.github_enabled
    fb = hub.submit("feature", "Webhooks", now=3.0)
    assert fb.issue_url == "https://github.com/me/app/issues/42"
    assert created["url"].endswith("/repos/me/app/issues")
    assert created["json"]["labels"] == ["feature", "needs-triage"]
    # Still stored locally as the source of truth.
    assert len(hub.list()) == 1


def test_github_failure_falls_back_to_local(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("api down")

    monkeypatch.setattr(feedback.requests, "post", boom)
    hub = feedback.FeedbackHub(store_path=str(tmp_path / "fb.json"),
                               github_repo="me/app", github_token="tok")
    fb = hub.submit("bug", "Still captured")
    assert fb.issue_url == ""  # API failed
    assert len(hub.list()) == 1  # but not lost
