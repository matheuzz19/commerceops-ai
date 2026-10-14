"""Real-Redis integration tests for durable intake, approval and inspection."""

import asyncio
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis import Redis

from commerceops.agents.planning import FinancePlan, InventoryPlan, SalesPlan
from commerceops.agents.runtime import SpecialistDependencies
from commerceops.agents.supervisor.graph import create_supervisor_graph
from commerceops.api.main import app
from commerceops.api.redis_runtime import RedisConversationRuntime
from commerceops.api.runtime import get_conversation_runtime
from commerceops.api.schemas import MessageRequest
from commerceops.gateway.storage import SessionConflict, session_key
from commerceops.graph.redis_checkpoints import RedisCheckpointSaver
from commerceops.graph.state import AgentTask, RoutingPlan
from commerceops.mcp.tools.schemas import ToolResult


class Planner:
    def __init__(self, plan) -> None:
        self.value = plan
        self.queries: list[str] = []

    async def plan(self, query: str):
        self.queries.append(query)
        return self.value


class Classifier:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def classify(self, query: str) -> RoutingPlan:
        self.queries.append(query)
        return RoutingPlan(tasks=[AgentTask(agent="finance", query=query, reason="Expense")])


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def call_tool(self, tool_name: str, arguments: Mapping[str, object]) -> ToolResult:
        assert tool_name == "create_transaction"
        self.calls.append(dict(arguments))
        await asyncio.sleep(0)
        return ToolResult(ok=True, data={"transaction": {
            "id": str(uuid4()), "order_id": None, "type": "EXPENSE", "status": "POSTED",
            "amount": arguments["amount"], "description": arguments["description"],
            "created_at": datetime.now(UTC).isoformat(),
        }}, error=None, audit_id=str(uuid4()))


def make_runtime(
    redis_context: tuple[Redis, str], *, amount: str = "10", debounce: float = 0,
    client: RecordingClient | None = None,
) -> tuple[RedisConversationRuntime, Classifier, Planner, RecordingClient]:
    redis, prefix = redis_context
    caller = client or RecordingClient()
    classifier = Classifier()
    planner = Planner(FinancePlan(
        action="create_expense", amount=Decimal(amount), description="Synthetic equipment",
    ))
    dependencies = SpecialistDependencies(
        sales_planner=Planner(SalesPlan(action="clarify")),
        inventory_planner=Planner(InventoryPlan(action="clarify")), finance_planner=planner,
        client_factory=lambda *args: caller,
    )
    graph = create_supervisor_graph(
        classifier, dependencies, checkpointer=RedisCheckpointSaver(redis, prefix + ":checkpoints"),
    )
    runtime = RedisConversationRuntime(
        graph, client=redis, prefix=prefix, debounce_seconds=debounce,
    )
    return runtime, classifier, planner, caller


def request(message_id: str = "1", *, debounce: bool = False, content: str = "Expense"):
    return MessageRequest(
        session_id="session", message_id=message_id, content=content, debounce=debounce,
    )


@pytest.mark.asyncio
async def test_split_messages_execute_once_and_preserve_every_source_id(redis_context) -> None:
    runtime, classifier, planner, caller = make_runtime(redis_context)
    tenant_id = str(uuid4())
    for index, content in enumerate(("Record an expense", "ten", "for equipment")):
        response = await runtime.submit(request(str(index), debounce=True, content=content),
                                        tenant_id, "operator")
        assert response.status == "buffered"
    assert caller.calls == []

    assert await runtime.flush_due() == 1
    assert await runtime.flush_due() == 0
    state = await runtime.session_state("session", tenant_id, "operator")

    assert state.status == "completed"
    assert state.source_message_ids == ["0", "1", "2"]
    assert state.state["normalized_message"]["source_message_ids"] == ["0", "1", "2"]
    assert classifier.queries == ["Record an expense\nten\nfor equipment"]
    assert len(planner.queries) == 1
    assert len(caller.calls) == 1
    duplicate = await runtime.submit(
        request("1", debounce=True, content="ten"), tenant_id, "operator",
    )
    assert duplicate.status == "completed"
    assert len(caller.calls) == 1


@pytest.mark.asyncio
async def test_debounce_deadline_is_reset_and_immediate_request_flushes_existing_buffer(
    redis_context,
) -> None:
    runtime, classifier, _, caller = make_runtime(redis_context, debounce=60)
    tenant_id = str(uuid4())
    await runtime.submit(
        request("1", debounce=True, content="Record expense"), tenant_id, "operator",
    )
    first = runtime.store.client.zscore(runtime.store.due_key, session_key(tenant_id, "session"))
    await runtime.submit(request("2", debounce=True, content="ten"), tenant_id, "operator")
    second = runtime.store.client.zscore(runtime.store.due_key, session_key(tenant_id, "session"))
    assert second >= first
    assert await runtime.flush_due() == 0
    assert caller.calls == []

    completed = await runtime.submit(request("3", content="for equipment"), tenant_id, "operator")

    assert completed.status == "completed"
    assert classifier.queries == ["Record expense\nten\nfor equipment"]
    assert len(caller.calls) == 1


@pytest.mark.asyncio
async def test_pending_approval_resumes_in_a_new_runtime_without_replanning(redis_context) -> None:
    first, _, planner, caller = make_runtime(redis_context, amount="1001")
    tenant_id = str(uuid4())
    pending = await first.submit(request(), tenant_id, "operator")
    assert pending.status == "requires_confirmation"
    assert caller.calls == []
    second, classifier, new_planner, _ = make_runtime(redis_context, amount="2001", client=caller)

    response = await second.resume(pending.checkpoint_id, tenant_id, "operator", approved=True)

    assert response.status == "completed"
    assert len(planner.queries) == 1
    assert new_planner.queries == classifier.queries == []
    assert len(caller.calls) == 1
    assert caller.calls[0]["amount"] == "1001"
    assert await first.resume(pending.checkpoint_id, tenant_id, "operator", approved=True) is None
    state = await second.session_state("session", tenant_id, "operator")
    assert state.status == "completed"
    assert state.result.checkpoint_id is None


@pytest.mark.asyncio
async def test_buffer_survives_restart_and_workers_do_not_duplicate_it(redis_context) -> None:
    first, _, _, caller = make_runtime(redis_context)
    tenant_id = str(uuid4())
    await first.submit(request(debounce=True), tenant_id, "operator")
    second, _, _, _ = make_runtime(redis_context, client=caller)

    counts = await asyncio.gather(first.flush_due(), second.flush_due())

    assert sum(counts) == 1
    assert len(caller.calls) == 1
    assert (await second.session_state("session", tenant_id, "operator")).status == "completed"


@pytest.mark.asyncio
async def test_approval_claim_is_atomic_across_runtime_instances(redis_context) -> None:
    first, _, _, caller = make_runtime(redis_context, amount="1001")
    tenant_id = str(uuid4())
    pending = await first.submit(request(), tenant_id, "operator")
    second, _, _, _ = make_runtime(redis_context, amount="1001", client=caller)

    outcomes = await asyncio.gather(
        first.resume(pending.checkpoint_id, tenant_id, "operator", approved=True),
        second.resume(pending.checkpoint_id, tenant_id, "operator", approved=True),
        return_exceptions=True,
    )

    assert sum(getattr(item, "status", None) == "completed" for item in outcomes) == 1
    assert len(caller.calls) == 1
    assert all(item is None or isinstance(item, SessionConflict) or item.status == "completed"
               for item in outcomes)


@pytest.mark.asyncio
async def test_session_and_receipts_cannot_cross_tenants_or_users(redis_context) -> None:
    runtime, _, _, caller = make_runtime(redis_context, amount="1001")
    tenant_id = str(uuid4())
    pending = await runtime.submit(request(), tenant_id, "operator")
    assert await runtime.session_state("session", str(uuid4()), "operator") is None
    with pytest.raises(SessionConflict) as wrong_user:
        await runtime.session_state("session", tenant_id, "other-user")
    assert wrong_user.value.status_code == 404
    outsider = await runtime.resume(
        pending.checkpoint_id, str(uuid4()), "operator", approved=True,
    )
    assert outsider is None
    outsider = await runtime.resume(
        pending.checkpoint_id, tenant_id, "other-user", approved=True,
    )
    assert outsider is None
    with pytest.raises(SessionConflict):
        await runtime.submit(request("2"), tenant_id, "operator")
    with pytest.raises(SessionConflict) as conflict:
        await runtime.submit(request(content="Different expense"), tenant_id, "operator")
    assert conflict.value.code == "MESSAGE_ID_CONFLICT"
    rejected = await runtime.resume(pending.checkpoint_id, tenant_id, "operator", approved=False)
    assert rejected.status == "failed"
    assert caller.calls == []
    assert (await runtime.submit(request(), tenant_id, "operator")).status == "failed"


@pytest.mark.asyncio
async def test_reused_session_keeps_one_thread_and_resets_results(redis_context) -> None:
    runtime, _, _, caller = make_runtime(redis_context)
    tenant_id = str(uuid4())
    first = await runtime.submit(request("1"), tenant_id, "operator")
    second = await runtime.submit(request("2"), tenant_id, "operator")
    state = await runtime.session_state("session", tenant_id, "operator")
    assert first.status == second.status == "completed"
    assert len(caller.calls) == 2
    assert len(state.state["specialist_results"]) == 1
    assert len(state.state["tool_results"]) == 1
    assert state.source_message_ids == ["2"]
    checkpoints = list(runtime.checkpointer.list({"configurable": {
        "thread_id": session_key(tenant_id, "session"), "checkpoint_ns": "",
    }}))
    assert len(checkpoints) > 10
    assert checkpoints[0].parent_config is not None


def test_api_background_worker_executes_buffer_and_exposes_scoped_state(redis_context) -> None:
    runtime, _, _, caller = make_runtime(redis_context, debounce=0.3)
    app.dependency_overrides[get_conversation_runtime] = lambda: runtime
    headers = {"X-Tenant-ID": str(uuid4()), "X-User-ID": "operator"}
    try:
        with TestClient(app) as client:
            for index, content in enumerate(("Record expense", "ten", "for equipment")):
                response = client.post("/messages", headers=headers, json=request(
                    str(index), debounce=True, content=content,
                ).model_dump())
                assert response.status_code == 200
                assert response.json()["status"] == "buffered"
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                state = client.get("/sessions/session/state", headers=headers)
                if state.json()["status"] == "completed":
                    break
                time.sleep(0.02)
            assert state.status_code == 200
            assert state.json()["status"] == "completed"
            assert state.json()["source_message_ids"] == ["0", "1", "2"]
            assert len(caller.calls) == 1
            outsider = client.get("/sessions/session/state", headers={
                **headers, "X-Tenant-ID": str(uuid4()),
            })
            assert outsider.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_interrupted_write_is_not_replayed_by_a_restarted_worker(redis_context) -> None:
    entered = asyncio.Event()

    class InterruptedClient(RecordingClient):
        async def call_tool(self, tool_name: str, arguments: Mapping[str, object]) -> ToolResult:
            self.calls.append(dict(arguments))
            entered.set()
            await asyncio.Event().wait()
            raise AssertionError("Interrupted call should never return.")

    caller = InterruptedClient()
    first, _, _, _ = make_runtime(redis_context, client=caller)
    tenant_id = str(uuid4())
    task = asyncio.create_task(first.submit(request(), tenant_id, "operator"))
    await asyncio.wait_for(entered.wait(), timeout=3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(caller.calls) == 1
    second, _, _, _ = make_runtime(redis_context, client=caller)

    assert await second.flush_due() == 1
    state = await second.session_state("session", tenant_id, "operator")

    assert state.status == "failed"
    assert state.result.error_code == "EXECUTION_INTERRUPTED"
    assert len(caller.calls) == 1
    assert (await second.submit(request(), tenant_id, "operator")).status == "failed"
    assert await second.flush_due() == 0


@pytest.mark.asyncio
async def test_recovery_republishes_interrupt_and_invalidates_stale_handle(redis_context) -> None:
    first, _, _, caller = make_runtime(redis_context, amount="1001")
    tenant_id = str(uuid4())
    pending = await first.submit(request(), tenant_id, "operator")
    digest = session_key(tenant_id, "session")
    async with first.store.lease(digest) as token:
        record = first.store.read(digest)
        # Simulate a process exiting after the graph checkpoint but before final metadata.
        record.status = "running"
        first.store.save(record, token, due=0)
    second, classifier, _, _ = make_runtime(redis_context, amount="2001", client=caller)

    assert await second.flush_due() == 1
    state = await second.session_state("session", tenant_id, "operator")

    assert state.status == "requires_confirmation"
    assert state.result.checkpoint_id != pending.checkpoint_id
    assert classifier.queries == []
    assert caller.calls == []
    assert await second.resume(pending.checkpoint_id, tenant_id, "operator", approved=True) is None
    completed = await second.resume(
        state.result.checkpoint_id, tenant_id, "operator", approved=True,
    )
    assert completed.status == "completed"
    assert caller.calls[0]["amount"] == "1001"


@pytest.mark.asyncio
async def test_fencing_prevents_an_expired_owner_from_overwriting_state(redis_context) -> None:
    runtime, _, _, _ = make_runtime(redis_context, debounce=60)
    tenant_id = str(uuid4())
    await runtime.submit(request(debounce=True), tenant_id, "operator")
    digest = session_key(tenant_id, "session")
    async with runtime.store.lease(digest) as token:
        record = runtime.store.read(digest)
        runtime.store.client.delete(runtime.store.key(digest) + ":lease")
        with pytest.raises(SessionConflict) as lost:
            runtime.store.save(record.model_copy(update={"status": "failed"}), token)
        assert lost.value.code == "SESSION_LEASE_LOST"
    assert runtime.store.read(digest).status == "buffered"


@pytest.mark.asyncio
async def test_execution_lease_renews_during_long_tool_calls(redis_context) -> None:
    entered = asyncio.Event()
    released = asyncio.Event()

    class SlowClient(RecordingClient):
        async def call_tool(self, tool_name: str, arguments: Mapping[str, object]) -> ToolResult:
            entered.set()
            await released.wait()
            return await super().call_tool(tool_name, arguments)

    caller = SlowClient()
    first, _, _, _ = make_runtime(redis_context, client=caller)
    first.store.lease_seconds = 1
    tenant_id = str(uuid4())
    task = asyncio.create_task(first.submit(request(), tenant_id, "operator"))
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        await asyncio.sleep(1.2)
        second, _, _, _ = make_runtime(redis_context, client=caller)
        assert await second.flush_due() == 0
    finally:
        released.set()
    assert (await task).status == "completed"
    assert len(caller.calls) == 1


@pytest.mark.asyncio
async def test_checkpoint_deletion_is_scoped_to_one_session_thread(redis_context) -> None:
    runtime, _, _, _ = make_runtime(redis_context)
    tenant_id = str(uuid4())
    await runtime.submit(request(), tenant_id, "operator")
    other = request().model_copy(update={"session_id": "other"})
    await runtime.submit(other, tenant_id, "operator")
    first_thread = session_key(tenant_id, "session")
    other_thread = session_key(tenant_id, "other")

    await runtime.checkpointer.adelete_thread(first_thread)

    first_snapshot = await runtime.checkpointer.aget_tuple(
        {"configurable": {"thread_id": first_thread}}
    )
    other_snapshot = await runtime.checkpointer.aget_tuple(
        {"configurable": {"thread_id": other_thread}}
    )
    assert first_snapshot is None
    assert other_snapshot is not None
