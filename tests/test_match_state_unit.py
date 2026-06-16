import pytest
from app.services import match_state_service as mss

# Pure unit tests — no DB. Opt out of the SQLite autouse harness fixtures.
pytestmark = pytest.mark.nodb


def test_call_status_transition_legal():
    assert mss.is_legal_call_status("none", "proposal_pending")
    assert mss.is_legal_call_status("proposal_pending", "scheduled")
    assert mss.is_legal_call_status("proposal_pending", "proposal_pending")  # counter supersede
    assert mss.is_legal_call_status("scheduled", "in_progress")
    assert mss.is_legal_call_status("in_progress", "pending_survey")
    assert mss.is_legal_call_status("pending_survey", "completed")
    assert mss.is_legal_call_status("scheduled", "no_show")
    assert mss.is_legal_call_status("no_show", "proposal_pending")  # reschedule


def test_call_status_transition_illegal():
    assert not mss.is_legal_call_status("none", "in_progress")
    assert not mss.is_legal_call_status("completed", "proposal_pending")
    assert not mss.is_legal_call_status("none", "scheduled")


@pytest.mark.parametrize("text,call,life,expected_substr", [
    ("open", "none", "active", "Texting"),
    ("open", "scheduled", "active", "Video date"),
    ("locked", "none", "active", "Schedule a video date"),
    ("locked", "proposal_pending", "active", "Review proposed time"),
    ("locked", "no_show", "active", "Missed"),
    ("open", "pending_survey", "active", "survey"),
    ("archived", "none", "expired", "expired"),
    ("archived", "none", "terminated", "ended"),
])
def test_card_display(text, call, life, expected_substr):
    s = mss.compute_match_card_display(text, call, life, hours_left=18,
                                       scheduled_start=None, is_proposer=False)
    assert expected_substr.lower() in s.lower()
