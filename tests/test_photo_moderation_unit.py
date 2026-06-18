import asyncio

import pytest

from app.services import photo_moderation_service as pm
from app.services.photo_moderation_service import (
    evaluate_safesearch, ModerationResult, LIKELIHOOD,
)

# Pure unit tests — no DB. Opt out of the SQLite autouse harness fixtures.
pytestmark = pytest.mark.nodb

L = LIKELIHOOD
DEFAULTS = {"adult_threshold": L["LIKELY"], "violence_threshold": L["LIKELY"]}


def _scores(adult="VERY_UNLIKELY", violence="VERY_UNLIKELY", racy="VERY_UNLIKELY"):
    return {"adult": L[adult], "violence": L[violence], "racy": L[racy]}


# ---- evaluate_safesearch (pure decision) ----

def test_clean_photo_allowed():
    r = evaluate_safesearch(_scores(), **DEFAULTS)
    assert isinstance(r, ModerationResult)
    assert r.allowed is True and r.status == "pass" and r.reason is None


@pytest.mark.parametrize("level", ["LIKELY", "VERY_LIKELY"])
def test_adult_at_or_above_threshold_blocks(level):
    r = evaluate_safesearch(_scores(adult=level), **DEFAULTS)
    assert r.allowed is False and r.status == "block" and r.reason


def test_adult_below_threshold_allowed():
    r = evaluate_safesearch(_scores(adult="POSSIBLE"), **DEFAULTS)
    assert r.allowed is True and r.status == "pass"


def test_violence_at_threshold_blocks():
    r = evaluate_safesearch(_scores(violence="LIKELY"), **DEFAULTS)
    assert r.allowed is False and r.status == "block"


def test_racy_very_likely_allowed_swimwear_case():
    # Dating photos routinely rate racy; must NOT block.
    r = evaluate_safesearch(_scores(racy="VERY_LIKELY"), **DEFAULTS)
    assert r.allowed is True and r.status == "pass"


def test_scores_echoed_into_result():
    s = _scores(adult="VERY_LIKELY")
    r = evaluate_safesearch(s, **DEFAULTS)
    assert r.scores == s


# ---- scan_image_url (wrapper: kill-switch, SSRF, retry, fail-open) ----

def _run(coro):
    return asyncio.run(coro)


def test_disabled_killswitch_passes_without_vision(monkeypatch):
    monkeypatch.setattr(pm, "PHOTO_SCAN_ENABLED", False)
    called = False

    def _boom(url):  # must NOT be called
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(pm, "_run_safesearch", _boom)
    r = _run(pm.scan_image_url("https://firebasestorage.googleapis.com/x"))
    assert r.status == "pass" and r.allowed is True and called is False


def test_non_allowlisted_host_fails_open_error(monkeypatch):
    monkeypatch.setattr(pm, "PHOTO_SCAN_ENABLED", True)
    r = _run(pm.scan_image_url("https://evil.example.com/internal"))
    assert r.status == "error" and r.allowed is True


def test_blocked_image(monkeypatch):
    monkeypatch.setattr(pm, "PHOTO_SCAN_ENABLED", True)
    monkeypatch.setattr(
        pm, "_run_safesearch",
        lambda url: {"adult": pm.LIKELIHOOD["VERY_LIKELY"], "violence": 0, "racy": 0},
    )
    r = _run(pm.scan_image_url(
        "https://firebasestorage.googleapis.com/v0/b/x/o/p?alt=media&token=t"))
    assert r.status == "block" and r.allowed is False


def test_vision_error_retries_then_fails_open(monkeypatch):
    monkeypatch.setattr(pm, "PHOTO_SCAN_ENABLED", True)
    calls = {"n": 0}

    def _flaky(url):
        calls["n"] += 1
        raise RuntimeError("vision down")

    monkeypatch.setattr(pm, "_run_safesearch", _flaky)
    r = _run(pm.scan_image_url("https://firebasestorage.googleapis.com/v0/b/x/o/p"))
    assert r.status == "error" and r.allowed is True
    assert calls["n"] == 2  # initial try + one retry
