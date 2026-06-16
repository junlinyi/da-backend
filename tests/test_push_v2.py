"""Unit tests for the Scheduling V2 typed push senders (Task 7.1).

Pure unit tests: we monkeypatch push_notification_service.send_push to capture
calls instead of hitting FCM, and use a lightweight fake recipient instead of a
DB User. Marked `nodb` so the SQLite autouse harness fixtures don't interfere
(same pattern as tests/test_match_state_unit.py).
"""
import pytest

from app.services import push_notification_service as push

pytestmark = pytest.mark.nodb


class _FakeUser:
    """Minimal stand-in for a User row for _push_enabled() + sends."""
    def __init__(self, name="Alex", device_token="tok-abcdef", opted_out=False):
        self.id = 1
        self.name = name
        self.device_token = device_token
        if opted_out:
            class _Prefs:
                push_notifications = False
            self.scheduling_preferences = _Prefs()
        else:
            self.scheduling_preferences = None


@pytest.fixture
def captured(monkeypatch):
    """Capture all send_push calls. Returns the list of kwargs dicts."""
    calls = []

    async def fake_send_push(token, title, body, data=None):
        calls.append({"token": token, "title": title, "body": body, "data": data or {}})
        return True

    monkeypatch.setattr(push, "send_push", fake_send_push)
    return calls


# --- Representative senders: sends when enabled, correct type + copy ---------

@pytest.mark.asyncio
async def test_text_locked_sends(captured):
    await push.notify_text_locked(_FakeUser(name="Mia"), peer_name="Mia", match_id=7)
    assert len(captured) == 1
    c = captured[0]
    assert c["token"] == "tok-abcdef"
    assert c["data"]["type"] == "text_locked"
    assert c["data"]["match_id"] == 7
    assert "video date" in c["body"]
    assert "Mia" in c["body"]


@pytest.mark.asyncio
async def test_text_window_5h_remaining_nudge(captured):
    await push.notify_text_window_5h_remaining(_FakeUser(), peer_name="Mia", match_id=3)
    assert captured[0]["data"]["type"] == "text_window_5h_remaining"
    assert "video date" in captured[0]["body"]
    assert "Mia" in captured[0]["body"]


@pytest.mark.asyncio
async def test_text_window_locking_nudge(captured):
    await push.notify_text_window_locking(_FakeUser(), peer_name="Mia", match_id=3)
    assert captured[0]["data"]["type"] == "text_window_locking"
    assert "video date" in captured[0]["body"]


@pytest.mark.asyncio
async def test_proposal_received(captured):
    await push.notify_proposal_received(_FakeUser(), peer_name="Mia", match_id=9, when="Thu 8 PM")
    c = captured[0]
    assert c["data"]["type"] == "proposal_received"
    assert "video date" in c["body"]
    assert "Mia" in c["body"]
    assert "Thu 8 PM" in c["body"]


@pytest.mark.asyncio
async def test_proposal_accepted(captured):
    await push.notify_proposal_accepted(_FakeUser(), peer_name="Mia", match_id=9, when="Thu 8 PM")
    assert captured[0]["data"]["type"] == "proposal_accepted"
    assert "video date" in captured[0]["body"]


@pytest.mark.asyncio
async def test_counter_proposal_received(captured):
    await push.notify_counter_proposal_received(_FakeUser(), peer_name="Mia", match_id=9, when="Fri 7 PM")
    c = captured[0]
    assert c["data"]["type"] == "counter_proposal_received"
    # Spec body copy has no "video date" (it's in the title); peer name + time in body.
    assert "video date" in c["title"]
    assert "Mia" in c["body"]
    assert "Fri 7 PM" in c["body"]


@pytest.mark.asyncio
async def test_date_starting_soon(captured):
    await push.notify_date_starting_soon(_FakeUser(), peer_name="Mia", match_id=4, minutes=15)
    c = captured[0]
    assert c["data"]["type"] == "date_starting_soon"
    assert "video date" in c["body"]
    assert "15 minutes" in c["body"]
    assert "Mia" in c["body"]


@pytest.mark.asyncio
async def test_date_starting_now(captured):
    await push.notify_date_starting_now(_FakeUser(), peer_name="Mia", match_id=4)
    assert captured[0]["data"]["type"] == "date_starting_now"
    assert "video date" in captured[0]["body"]


@pytest.mark.asyncio
async def test_date_no_show_reschedule(captured):
    await push.notify_date_no_show_reschedule(_FakeUser(), peer_name="Mia", match_id=4)
    assert captured[0]["data"]["type"] == "date_no_show_reschedule"
    assert "video date" in captured[0]["body"]
    assert "Mia" in captured[0]["body"]


@pytest.mark.asyncio
async def test_match_terminated_no_show(captured):
    await push.notify_match_terminated_no_show(_FakeUser(), peer_name="Mia", match_id=4)
    assert captured[0]["data"]["type"] == "match_terminated_no_show"
    assert "Mia" in captured[0]["body"]


@pytest.mark.asyncio
async def test_match_expired_unscheduled(captured):
    await push.notify_match_expired_unscheduled(_FakeUser(), peer_name="Mia", match_id=4)
    assert captured[0]["data"]["type"] == "match_expired_unscheduled"
    assert "video date" in captured[0]["body"]


@pytest.mark.asyncio
async def test_exit_survey_prompt(captured):
    await push.notify_exit_survey_prompt(_FakeUser(), peer_name="Mia", match_id=4)
    assert captured[0]["data"]["type"] == "exit_survey_prompt"
    assert "video date" in captured[0]["body"]


@pytest.mark.asyncio
async def test_partner_responded_yes(captured):
    await push.notify_partner_responded_yes(_FakeUser(), peer_name="Mia", match_id=4)
    assert captured[0]["data"]["type"] == "partner_responded_yes"
    assert "Mia" in captured[0]["body"]


@pytest.mark.asyncio
async def test_text_unlocked_mutual_yes(captured):
    await push.notify_text_unlocked_mutual_yes(_FakeUser(), peer_name="Mia", match_id=4)
    assert captured[0]["data"]["type"] == "text_unlocked_mutual_yes"
    assert "Mia" in captured[0]["body"]


# --- Asymmetric copy: match_terminated_survey_no ----------------------------

@pytest.mark.asyncio
async def test_terminated_survey_no_asymmetric(captured):
    # To the no-er
    await push.notify_match_terminated_survey_no(
        _FakeUser(), peer_name="Mia", match_id=4, is_no_er=True)
    # To the other
    await push.notify_match_terminated_survey_no(
        _FakeUser(), peer_name="Mia", match_id=4, is_no_er=False)
    assert len(captured) == 2
    no_er, other = captured
    assert no_er["data"]["type"] == "match_terminated_survey_no"
    assert no_er["body"] == "Got it — we've ended this match."
    assert other["body"] == "It wasn't a mutual match this time."


# --- Gating: no-op when push disabled ---------------------------------------

@pytest.mark.asyncio
async def test_no_send_when_no_device_token(captured):
    user = _FakeUser(device_token=None)
    await push.notify_text_locked(user, peer_name="Mia", match_id=7)
    await push.notify_proposal_received(user, peer_name="Mia", match_id=7)
    await push.notify_date_starting_soon(user, peer_name="Mia", match_id=7)
    await push.notify_match_terminated_survey_no(user, peer_name="Mia", match_id=7, is_no_er=True)
    assert captured == []


@pytest.mark.asyncio
async def test_no_send_when_opted_out(captured):
    user = _FakeUser(opted_out=True)
    await push.notify_text_unlocked_mutual_yes(user, peer_name="Mia", match_id=7)
    assert captured == []
