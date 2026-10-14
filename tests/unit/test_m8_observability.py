import json
import logging
from decimal import Decimal
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from prometheus_client.parser import text_string_to_metric_families

from commerceops.config import settings
from commerceops.observability.logging import IDENTITY, JsonFormatter, event, logger
from commerceops.observability.metrics import REGISTRY, render_metrics
from commerceops.observability.tracing import ObservationCallback, observed_invoke, tracing_client


def test_formatter_omits_content_arguments_and_exception_text() -> None:
    record = logging.LogRecord("test", logging.ERROR, "", 1, "secret credential", (), None)
    record.safe_fields = {
        "event": "tool_result",
        "error_code": "TOOL_FAILED",
        "content": "secret prompt",
        "arguments": {"api_key": "secret"},
    }
    encoded = JsonFormatter().format(record)
    assert "secret" not in encoded
    assert json.loads(encoded)["error_code"] == "TOOL_FAILED"


def test_langsmith_client_hides_all_nested_io(monkeypatch: pytest.MonkeyPatch) -> None:
    options: dict[str, object] = {}

    def fake_client(**kwargs: object) -> object:
        options.update(kwargs)
        return object()

    monkeypatch.setattr(settings, "langsmith_tracing", True)
    monkeypatch.setattr(settings, "langsmith_api_key", "synthetic-test-key")
    monkeypatch.setattr("commerceops.observability.tracing.Client", fake_client)
    tracing_client.cache_clear()
    try:
        assert tracing_client() is not None
        assert options["hide_inputs"] is True
        assert options["hide_outputs"] is True
    finally:
        tracing_client.cache_clear()


def test_usage_and_explicit_cost_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    callback = ObservationCallback()
    incoming = (
        REGISTRY.get_sample_value("commerceops_llm_tokens_total", {"direction": "input"}) or 0
    )
    outgoing = (
        REGISTRY.get_sample_value("commerceops_llm_tokens_total", {"direction": "output"}) or 0
    )
    response = LLMResult(
        generations=[
            [
                ChatGeneration(
                    message=AIMessage(
                        content="unlogged secret",
                        usage_metadata={
                            "input_tokens": 100,
                            "output_tokens": 50,
                            "total_tokens": 150,
                        },
                    )
                )
            ]
        ]
    )
    callback.on_llm_end(response, run_id=uuid4())
    assert callback.input_tokens == 100
    assert callback.output_tokens == 50
    monkeypatch.setattr(settings, "llm_input_usd_per_million", None)
    assert callback.cost_usd is None
    monkeypatch.setattr(settings, "llm_input_usd_per_million", Decimal("2"))
    monkeypatch.setattr(settings, "llm_output_usd_per_million", Decimal("8"))
    assert callback.cost_usd == pytest.approx(0.0006)
    assert REGISTRY.get_sample_value("commerceops_llm_tokens_total", {"direction": "input"}) == (
        incoming + 100
    )
    assert REGISTRY.get_sample_value("commerceops_llm_tokens_total", {"direction": "output"}) == (
        outgoing + 50
    )


@pytest.mark.asyncio
async def test_graph_failure_is_counted_and_context_is_reset(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class BrokenGraph:
        async def ainvoke(self, payload: object, config: object) -> object:
            raise RuntimeError("secret failure payload")

    before = REGISTRY.get_sample_value("commerceops_graph_runs_total", {"status": "failed"}) or 0
    original = IDENTITY.get()
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.INFO, logger=logger.name), pytest.raises(RuntimeError):
            await observed_invoke(
                BrokenGraph(),
                {"tenant_id": "synthetic-tenant", "session_id": "synthetic-session"},
                config={},
                tracing_enabled=False,
            )
        assert IDENTITY.get() == original
        events = [getattr(record, "safe_fields", {}) for record in caplog.records]
        assert any(row.get("error_code") == "GRAPH_EXECUTION_FAILED" for row in events)
        assert "secret failure" not in json.dumps(events)
        assert REGISTRY.get_sample_value("commerceops_graph_runs_total", {"status": "failed"}) == (
            before + 1
        )
    finally:
        logger.removeHandler(caplog.handler)


def test_prometheus_output_has_no_identity_labels() -> None:
    families = list(text_string_to_metric_families(render_metrics().decode()))
    assert families
    for family in families:
        for sample in family.samples:
            assert not {"tenant_id", "session_id", "request_id"}.intersection(sample.labels)


def test_context_events_are_correlated(caplog: pytest.LogCaptureFixture) -> None:
    token = IDENTITY.set({"request_id": "synthetic-request", "tenant_id": "synthetic-tenant"})
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.INFO, logger=logger.name):
            event("hitl_pause")
        fields = caplog.records[-1].safe_fields
        assert fields["request_id"] == "synthetic-request"
        assert fields["event"] == "hitl_pause"
    finally:
        IDENTITY.reset(token)
        logger.removeHandler(caplog.handler)


def test_export_sanitizer_removes_payloads_errors_and_model_configuration() -> None:
    from commerceops.observability.tracing import sanitize_run_ops

    original = {
        "id": "synthetic-run",
        "inputs": {"prompt": "secret"},
        "outputs": {"content": "secret"},
        "serialized": {"api_key": "secret"},
        "error": "secret exception",
        "events": [{"exception": "secret"}],
        "extra": {
            "metadata": {"request_id": "synthetic-request", "secret": "value"},
            "invocation_params": {"api_key": "secret"},
        },
    }
    cleaned = sanitize_run_ops([original])[0]
    assert cleaned["id"] == original["id"]
    assert "secret" not in json.dumps(cleaned)
    assert original["inputs"]["prompt"] == "secret"
