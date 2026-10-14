from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from commerceops.api.schemas import MessageRequest
from commerceops.gateway.storage import (
    BufferedMessage,
    SessionConflict,
    aggregate_messages,
    message_fingerprint,
    session_key,
)


def test_text_fragments_aggregate_in_arrival_order() -> None:
    messages = [BufferedMessage(
        request=MessageRequest(
            session_id="session", message_id=str(index), content=content, debounce=True,
        ), timestamp=datetime.now(UTC),
    ) for index, content in enumerate(("Create an order", "for Synthetic", "two keyboards"))]

    combined = aggregate_messages(messages)

    assert combined.content == "Create an order\nfor Synthetic\ntwo keyboards"
    assert combined.message_id == "2"
    assert combined.session_id == "session"
    assert combined.debounce is False


def test_invalid_aggregation_and_non_text_debounce_are_rejected() -> None:
    with pytest.raises(ValueError):
        aggregate_messages([])
    with pytest.raises(ValidationError):
        MessageRequest(session_id="session", message_id="1", content="Audio",
                       content_type="audio", debounce=True)
    text = BufferedMessage(request=MessageRequest(
        session_id="session", message_id="1", content="Text",
    ), timestamp=datetime.now(UTC))
    audio = BufferedMessage(request=MessageRequest(
        session_id="session", message_id="2", content="Audio", content_type="audio",
    ), timestamp=datetime.now(UTC))
    with pytest.raises(SessionConflict):
        aggregate_messages([text, audio])


def test_session_keys_are_tenant_scoped_and_unambiguous() -> None:
    assert session_key("tenant-1", "session") != session_key("tenant-2", "session")
    assert session_key("a:b", "c") != session_key("a", "b:c")


def test_retries_keep_message_identity_when_debounce_changes() -> None:
    first = MessageRequest(session_id="session", message_id="1", content="Text", debounce=True)
    retry = first.model_copy(update={"debounce": False})
    assert message_fingerprint(first) == message_fingerprint(retry)
