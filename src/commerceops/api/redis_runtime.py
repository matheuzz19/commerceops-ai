"""M7 durable intake, session ownership, debounce worker and approval recovery."""

import asyncio
import json
import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from langgraph.types import Command
from redis import Redis
from redis.exceptions import RedisError

from commerceops.api.runtime import ConversationRuntime
from commerceops.api.schemas import MessageRequest, MessageResponse, SessionStateResponse
from commerceops.config import settings
from commerceops.gateway.storage import (
    BufferedMessage,
    MessageReceipt,
    RedisSessionStore,
    SessionConflict,
    SessionRecord,
    aggregate_messages,
    message_fingerprint,
    session_key,
)
from commerceops.graph.checkpoints import RedisPendingCheckpointStore
from commerceops.graph.redis_checkpoints import RedisCheckpointSaver

logger = logging.getLogger(__name__)

PUBLIC_STATE = (
    "normalized_message", "routing_plan", "resolved_entities", "proposed_actions",
    "tool_results", "specialist_results", "confirmation_request", "error", "final_response",
)


class RedisConversationRuntime(ConversationRuntime):
    def __init__(
        self, graph: Any | None = None, *, client: Redis | None = None,
        prefix: str = "commerceops", debounce_seconds: float | None = None,
        lease_seconds: float | None = None,
    ) -> None:
        active_client = client or Redis.from_url(
            settings.redis_url, socket_connect_timeout=3, socket_timeout=3,
        )
        self.store = RedisSessionStore(
            active_client, prefix, lease_seconds or settings.session_lock_seconds,
        )
        super().__init__(graph, RedisPendingCheckpointStore(active_client, prefix + ":pending"))
        self.checkpointer = RedisCheckpointSaver(active_client, prefix + ":checkpoints")
        self.debounce_seconds = (
            settings.message_debounce_seconds if debounce_seconds is None else debounce_seconds
        )

    @staticmethod
    def _verify_owner(record: SessionRecord, tenant_id: str, user_id: str) -> None:
        if record.tenant_id != tenant_id or record.user_id != user_id:
            raise SessionConflict("SESSION_NOT_FOUND", "Session not found.", 404)

    async def _duplicate(
        self, digest: str, request: MessageRequest,
    ) -> MessageResponse | None:
        receipt = await asyncio.to_thread(self.store.receipt, digest, request.message_id)
        if receipt is None:
            return None
        if receipt.fingerprint != message_fingerprint(request):
            raise SessionConflict("MESSAGE_ID_CONFLICT", "The message ID was already used.")
        return receipt.response

    async def submit(
        self, request: MessageRequest, tenant_id: str, user_id: str,
    ) -> MessageResponse:
        digest = session_key(tenant_id, request.session_id)
        previous = await asyncio.to_thread(self.store.read, digest)
        if previous is not None:
            self._verify_owner(previous, tenant_id, user_id)
            duplicate = await self._duplicate(digest, request)
            if duplicate is not None:
                return duplicate
        async with self.store.lease(digest) as token:
            record = await asyncio.to_thread(self.store.read, digest)
            if record is None:
                record = SessionRecord(
                    tenant_id=tenant_id, user_id=user_id, session_id=request.session_id,
                    thread_id=digest, status="buffered",
                )
            self._verify_owner(record, tenant_id, user_id)
            duplicate = await self._duplicate(digest, request)
            if duplicate is not None:
                return duplicate
            if record.status in {"running", "requires_confirmation"}:
                raise SessionConflict("SESSION_BUSY", "Resolve the pending session request first.")
            if record.buffer and request.content_type != "text":
                raise SessionConflict(
                    "INCOMPATIBLE_BUFFER", "Only text messages can be aggregated."
                )
            response = MessageResponse(
                status="buffered", response=None, checkpoint_id=None, trace_id=str(uuid4()),
            )
            record.buffer.append(BufferedMessage(request=request, timestamp=datetime.now(UTC)))
            record.status = "buffered"
            record.result = response
            record.source_message_ids = [item.request.message_id for item in record.buffer]
            now = await asyncio.to_thread(self.store.now)
            await asyncio.to_thread(
                self.store.save, record, token,
                {request.message_id: MessageReceipt(
                    fingerprint=message_fingerprint(request), response=response,
                )},
                now + self.debounce_seconds,
            )
            if request.debounce:
                return response
            return await self._run_buffer(record, token)

    async def _save_result(
        self, record: SessionRecord, token: bytes, response: MessageResponse,
    ) -> MessageResponse:
        previous_handle = record.result.checkpoint_id if record.result else None
        record.status = response.status
        record.result = response
        digest = session_key(record.tenant_id, record.session_id)
        receipts: dict[str, MessageReceipt] = {}
        for message_id in record.source_message_ids:
            old = await asyncio.to_thread(self.store.receipt, digest, message_id)
            if old is not None:
                receipts[message_id] = old.model_copy(update={"response": response})
        await asyncio.to_thread(self.store.save, record, token, receipts)
        if previous_handle and previous_handle != response.checkpoint_id:
            await asyncio.to_thread(self.pending.remove, previous_handle)
        return response

    async def _response_for_session(
        self, result: dict[str, Any], record: SessionRecord, trace_id: str,
    ) -> MessageResponse:
        config = {"configurable": {"thread_id": record.thread_id}}
        response = await asyncio.to_thread(
            self._response, result, trace_id, str(uuid4()),
            record.tenant_id, record.user_id, config,
        )
        if response.checkpoint_id is not None:
            pending = await asyncio.to_thread(self.pending.get, response.checkpoint_id)
            if pending is not None:
                await asyncio.to_thread(
                    self.pending.put, replace(pending, session_id=record.session_id),
                )
        return response

    @staticmethod
    def _failed(trace_id: str, code: str) -> MessageResponse:
        return MessageResponse(
            status="failed", response="The operation could not be completed safely. "
            "Inspect the session and business records before submitting a replacement request.",
            checkpoint_id=None, trace_id=trace_id, error_code=code,
        )

    async def _run_buffer(self, record: SessionRecord, token: bytes) -> MessageResponse:
        messages = list(record.buffer)
        request = aggregate_messages(messages)
        record.buffer = []
        record.source_message_ids = [item.request.message_id for item in messages]
        record.execution_id = str(uuid4())
        record.status = "running"
        trace_id = record.result.trace_id if record.result else str(uuid4())
        await asyncio.to_thread(self.store.save, record, token, due=0)
        try:
            result = await self.graph.ainvoke({
                "tenant_id": record.tenant_id, "user_id": record.user_id,
                "session_id": record.session_id, "message_id": request.message_id,
                "content": request.content, "content_type": request.content_type,
                "timestamp": messages[-1].timestamp,
                "source_message_ids": record.source_message_ids,
                "execution_id": record.execution_id,
            }, config={"configurable": {"thread_id": record.thread_id}})
            response = await self._response_for_session(result, record, trace_id)
        except RedisError:
            raise
        except Exception:
            response = self._failed(trace_id, "GRAPH_EXECUTION_FAILED")
        return await self._save_result(record, token, response)

    async def resume(
        self, checkpoint_id: str, tenant_id: str, user_id: str, *, approved: bool,
    ) -> MessageResponse | None:
        pending = await asyncio.to_thread(self.pending.get, checkpoint_id)
        if pending is None or pending.tenant_id != tenant_id or pending.user_id != user_id:
            return None
        if pending.session_id is None:
            return None
        digest = session_key(tenant_id, pending.session_id)
        async with self.store.lease(digest) as token:
            record = await asyncio.to_thread(self.store.read, digest)
            if record is None:
                return None
            self._verify_owner(record, tenant_id, user_id)
            if record.status != "requires_confirmation" or record.result is None:
                return None
            if record.result.checkpoint_id != checkpoint_id:
                return None
            claimed = await asyncio.to_thread(self.pending.claim, checkpoint_id, tenant_id, user_id)
            if claimed is None:
                return None
            record.status = "running"
            trace_id = str(uuid4())
            await asyncio.to_thread(self.store.save, record, token, due=0)
            try:
                result = await self.graph.ainvoke(Command(resume={
                    interrupt_id: {"approved": approved} for interrupt_id in claimed.interrupt_ids
                }), config=claimed.config)
                response = await self._response_for_session(result, record, trace_id)
            except RedisError:
                raise
            except Exception:
                response = self._failed(trace_id, "APPROVAL_EXECUTION_FAILED")
            return await self._save_result(record, token, response)

    async def session_state(
        self, session_id: str, tenant_id: str, user_id: str,
    ) -> SessionStateResponse | None:
        record = await asyncio.to_thread(self.store.read, session_key(tenant_id, session_id))
        if record is None:
            return None
        self._verify_owner(record, tenant_id, user_id)
        values: dict[str, Any] = {}
        if record.status not in {"buffered", "running"}:
            saved = await self.checkpointer.aget_tuple(
                {"configurable": {"thread_id": record.thread_id}}
            )
            channels = saved.checkpoint["channel_values"] if saved is not None else {}
            if channels.get("execution_id") == record.execution_id:
                values = jsonable_encoder({key: channels[key] for key in PUBLIC_STATE
                                          if key in channels})
        return SessionStateResponse(
            session_id=session_id, status=record.status, result=record.result,
            source_message_ids=record.source_message_ids, state=values,
        )

    async def _recover(self, record: SessionRecord, token: bytes) -> None:
        snapshot = await self.graph.aget_state({"configurable": {"thread_id": record.thread_id}})
        trace_id = record.result.trace_id if record.result else str(uuid4())
        interrupts = [item for task in snapshot.tasks for item in task.interrupts]
        if snapshot.values.get("execution_id") != record.execution_id:
            response = self._failed(trace_id, "EXECUTION_INTERRUPTED")
        elif interrupts or not snapshot.next:
            # Recover already-saved outcomes, never reinvoke unfinished write nodes.
            result = dict(snapshot.values)
            if interrupts:
                result["__interrupt__"] = interrupts
            response = await self._response_for_session(result, record, trace_id)
        else:
            response = self._failed(trace_id, "EXECUTION_INTERRUPTED")
        await self._save_result(record, token, response)

    async def flush_due(self) -> int:
        completed = 0
        for digest in await asyncio.to_thread(self.store.due):
            try:
                async with self.store.lease(digest) as token:
                    record = await asyncio.to_thread(self.store.read, digest)
                    if record is None:
                        await asyncio.to_thread(self.store.client.zrem, self.store.due_key, digest)
                        continue
                    score = await asyncio.to_thread(
                        self.store.client.zscore, self.store.due_key, digest
                    )
                    if score is None or score > await asyncio.to_thread(self.store.now):
                        continue
                    if record.status == "running":
                        await self._recover(record, token)
                    elif record.status == "buffered" and record.buffer:
                        await self._run_buffer(record, token)
                    else:
                        await asyncio.to_thread(self.store.save, record, token)
                    completed += 1
            except SessionConflict as error:
                if error.code != "SESSION_BUSY":
                    raise
        return completed

    async def worker_loop(self) -> None:
        while True:
            try:
                await self.flush_due()
            except (RedisError, SessionConflict):
                logger.warning(json.dumps({
                    "event": "buffer_worker_error", "code": "STATE_STORE_UNAVAILABLE",
                }))
            await asyncio.sleep(0.2)

    async def close(self) -> None:
        await asyncio.to_thread(self.store.client.close)
