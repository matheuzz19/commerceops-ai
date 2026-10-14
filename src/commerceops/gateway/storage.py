"""Redis session records, message receipts and renewable execution leases."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from hashlib import sha256
from typing import Literal, cast

from pydantic import BaseModel, Field
from redis import Redis
from redis.exceptions import RedisError

from commerceops.api.schemas import MessageRequest, MessageResponse


class SessionConflict(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class BufferedMessage(BaseModel):
    request: MessageRequest
    timestamp: datetime


class MessageReceipt(BaseModel):
    fingerprint: str
    response: MessageResponse


class SessionRecord(BaseModel):
    tenant_id: str
    user_id: str
    session_id: str
    thread_id: str
    status: Literal["buffered", "running", "requires_confirmation", "completed", "failed"]
    buffer: list[BufferedMessage] = Field(default_factory=list)
    source_message_ids: list[str] = Field(default_factory=list)
    execution_id: str | None = None
    result: MessageResponse | None = None


def session_key(tenant_id: str, session_id: str) -> str:
    return sha256(json.dumps([tenant_id, session_id]).encode()).hexdigest()


def message_fingerprint(request: MessageRequest) -> str:
    return sha256(json.dumps([request.content, request.content_type]).encode()).hexdigest()


def aggregate_messages(messages: list[BufferedMessage]) -> MessageRequest:
    if not messages:
        raise ValueError("Cannot aggregate an empty message buffer.")
    if any(item.request.content_type != "text" for item in messages):
        if len(messages) != 1:
            raise SessionConflict("INCOMPATIBLE_BUFFER", "Only text messages can be aggregated.")
        return messages[0].request.model_copy(update={"debounce": False})
    latest = messages[-1].request
    return MessageRequest(
        session_id=latest.session_id, message_id=latest.message_id,
        content="\n".join(item.request.content for item in messages), debounce=False,
    )


class RedisSessionStore:
    def __init__(
        self, client: Redis, prefix: str = "commerceops", lease_seconds: float = 60,
    ) -> None:
        self.client = client
        self.prefix = prefix
        self.lease_seconds = lease_seconds
        self.due_key = prefix + ":due"

    def key(self, digest: str) -> str:
        return f"{self.prefix}:sessions:{digest}"

    def read(self, digest: str) -> SessionRecord | None:
        raw = self.client.get(self.key(digest))
        return SessionRecord.model_validate_json(raw) if raw else None

    def receipt(self, digest: str, message_id: str) -> MessageReceipt | None:
        raw = self.client.hget(self.key(digest) + ":receipts", message_id)
        return MessageReceipt.model_validate_json(raw) if raw else None

    def now(self) -> float:
        seconds, microseconds = self.client.time()
        return float(seconds) + float(microseconds) / 1_000_000

    def due(self) -> list[str]:
        keys = cast(list[bytes], self.client.zrangebyscore(
            self.due_key, "-inf", self.now(), start=0, num=20,
        ))
        return [key.decode() for key in keys]

    def save(
        self, record: SessionRecord, token: bytes,
        receipts: dict[str, MessageReceipt] | None = None, due: float | None = None,
    ) -> None:
        digest = session_key(record.tenant_id, record.session_id)
        args: list[bytes | str | float] = [
            token, digest, record.model_dump_json(), "" if due is None else due,
        ]
        for message_id, receipt in (receipts or {}).items():
            args.extend([message_id, receipt.model_dump_json()])
        result = self.client.eval(
            """
            if redis.call('GET', KEYS[2]) ~= ARGV[1] then return 0 end
            redis.call('SET', KEYS[1], ARGV[3])
            if ARGV[4] == '' then
                redis.call('ZREM', KEYS[3], ARGV[2])
            else
                redis.call('ZADD', KEYS[3], ARGV[4], ARGV[2])
            end
            for i = 5, #ARGV, 2 do redis.call('HSET', KEYS[4], ARGV[i], ARGV[i+1]) end
            return 1
            """,
            4, self.key(digest), self.key(digest) + ":lease", self.due_key,
            self.key(digest) + ":receipts", *args,
        )
        if not result:
            raise SessionConflict("SESSION_LEASE_LOST", "Session execution ownership was lost.")

    @asynccontextmanager
    async def lease(self, digest: str) -> AsyncIterator[bytes]:
        lock = self.client.lock(
            self.key(digest) + ":lease", timeout=self.lease_seconds,
            blocking_timeout=0, thread_local=False,
        )
        if not await asyncio.to_thread(lock.acquire, blocking=False):
            raise SessionConflict("SESSION_BUSY", "The session is currently processing a request.")
        owner = asyncio.current_task()

        async def renew() -> None:
            while True:
                await asyncio.sleep(self.lease_seconds / 3)
                try:
                    await asyncio.to_thread(lock.extend, self.lease_seconds, replace_ttl=True)
                except RedisError:
                    if owner is not None:
                        owner.cancel()
                    return

        renewal = asyncio.create_task(renew())
        try:
            yield lock.local.token
        finally:
            renewal.cancel()
            with suppress(asyncio.CancelledError):
                await renewal
            with suppress(RedisError):
                await asyncio.to_thread(lock.release)
