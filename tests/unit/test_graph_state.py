from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from commerceops.agents.supervisor.nodes import normalize_message
from commerceops.graph.state import AgentState, NormalizedMessage


def test_normalized_message_rejects_empty_content() -> None:
    with pytest.raises(ValidationError):
        NormalizedMessage(
            tenant_id="tenant",
            user_id="user",
            session_id="session",
            message_id="message",
            content="",
            timestamp=datetime.now(UTC),
        )


def test_normalize_message_preserves_trusted_identity() -> None:
    state: AgentState = {
        "tenant_id": " tenant-one ",
        "user_id": " user-one ",
        "session_id": " session-one ",
        "message_id": " message-one ",
        "content": "  Show inventory  ",
        "content_type": "text",
    }

    update = normalize_message(state)
    message = update["normalized_message"]

    assert isinstance(message, NormalizedMessage)
    assert message.tenant_id == "tenant-one"
    assert message.user_id == "user-one"
    assert message.content == "Show inventory"


def test_normalize_message_rejects_whitespace_only_identity() -> None:
    state: AgentState = {
        "tenant_id": "   ",
        "user_id": "user",
        "session_id": "session",
        "message_id": "message",
        "content": "hello",
    }

    with pytest.raises(ValidationError):
        normalize_message(state)
