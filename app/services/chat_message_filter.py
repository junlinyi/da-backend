"""Chat message content filter.

V1 stub for Scheduling V2: a placeholder phone-number masking regex. The full
masking/moderation algorithm (AI + richer heuristics) is deferred to the
dedicated moderation spec. This module's PUBLIC interface
(`filter_message_content`) is stable; only the implementation will change.
"""
import re

# 3-3-4 digit phone pattern with optional separators / parens around the area
# code, e.g. "555-123-4567", "555.123.4567", "(555) 123 4567", "5551234567".
_PHONE = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")


def filter_message_content(content: str) -> tuple[str, bool]:
    """Return (filtered_content, has_masked_content).

    V1 stub — full algorithm deferred to the moderation spec.
    """
    if _PHONE.search(content):
        return _PHONE.sub("[phone hidden]", content), True
    return content, False
