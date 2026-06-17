import pytest
from app.services.chat_message_filter import filter_message_content

# Pure unit tests — no DB. Opt out of the SQLite autouse harness fixtures.
pytestmark = pytest.mark.nodb


@pytest.mark.parametrize("raw", ["call me 555-123-4567", "555.123.4567", "(555) 123 4567"])
def test_masks_phone(raw):
    filtered, masked = filter_message_content(raw)
    assert masked is True and "[phone hidden]" in filtered


def test_clean_passthrough():
    filtered, masked = filter_message_content("hey how are you")
    assert masked is False and filtered == "hey how are you"
