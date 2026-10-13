"""Plain-Redis LangGraph saver with typed snapshots and atomic pending writes."""

import asyncio
import json
from collections.abc import AsyncIterator, Iterator, Sequence
from hashlib import sha256
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from redis import Redis

STATE_TYPES = [
    ("commerceops.graph.state", name) for name in (
        "NormalizedMessage", "RouteDecision", "AgentTask", "RoutingPlan",
        "SpecialistResult", "ResolvedEntity", "ProposedAction", "PreparedWrite",
    )
]


class RedisCheckpointSaver(BaseCheckpointSaver[int]):
    def __init__(self, client: Redis, prefix: str = "commerceops:checkpoints") -> None:
        if client.connection_pool.connection_kwargs.get("decode_responses"):
            raise ValueError("Checkpoint storage requires a binary Redis client.")
        super().__init__(serde=JsonPlusSerializer(allowed_msgpack_modules=STATE_TYPES))
        self.client = client
        self.prefix = prefix

    def _key(self, config: RunnableConfig) -> str:
        values = config["configurable"]
        identity = json.dumps([values["thread_id"], values.get("checkpoint_ns", "")])
        return f"{self.prefix}:{sha256(identity.encode()).hexdigest()}"

    def _encode(self, value: Any) -> bytes:
        kind, payload = self.serde.dumps_typed(value)
        return kind.encode() + b"\n" + payload

    def _decode(self, value: bytes | str) -> Any:
        if not isinstance(value, bytes):
            raise ValueError("Checkpoint storage requires binary values.")
        kind, payload = value.split(b"\n", 1)
        return self.serde.loads_typed((kind.decode(), payload))

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        key = self._key(config)
        checkpoint_id = get_checkpoint_id(config)
        if not checkpoint_id:
            latest = cast(list[bytes], self.client.zrevrange(key + ":index", 0, 0))
            if not latest:
                return None
            checkpoint_id = latest[0].decode()
        raw = self.client.hget(key, checkpoint_id)
        if raw is None:
            return None
        saved = self._decode(raw)
        writes = self.client.hgetall(f"{key}:writes:{checkpoint_id}")
        return CheckpointTuple(
            config=saved["config"], checkpoint=saved["checkpoint"], metadata=saved["metadata"],
            parent_config=saved["parent"],
            pending_writes=[self._decode(value) for _, value in sorted(writes.items())],
        )

    def put(
        self, config: RunnableConfig, checkpoint: Checkpoint,
        metadata: CheckpointMetadata, new_versions: ChannelVersions,
    ) -> RunnableConfig:
        updated: RunnableConfig = {"configurable": {
            "thread_id": config["configurable"]["thread_id"],
            "checkpoint_ns": config["configurable"].get("checkpoint_ns", ""),
            "checkpoint_id": checkpoint["id"],
        }}
        saved = {
            "config": updated, "checkpoint": checkpoint,
            "metadata": get_checkpoint_metadata(config, metadata),
            "parent": {"configurable": {
                **updated["configurable"], "checkpoint_id": get_checkpoint_id(config),
            }} if get_checkpoint_id(config) else None,
        }
        key = self._key(config)
        with self.client.pipeline() as pipe:
            pipe.hset(key, checkpoint["id"], self._encode(saved))
            # Monotonic IDs are ordered lexicographically with equal scores.
            pipe.zadd(key + ":index", {checkpoint["id"]: 0})
            pipe.sadd(self.prefix + ":threads:" + str(config["configurable"]["thread_id"]), key)
            pipe.execute()
        return updated

    def put_writes(
        self, config: RunnableConfig, writes: Sequence[tuple[str, Any]],
        task_id: str, task_path: str = "",
    ) -> None:
        key = f"{self._key(config)}:writes:{get_checkpoint_id(config)}"
        with self.client.pipeline() as pipe:
            for index, (channel, value) in enumerate(writes):
                index = WRITES_IDX_MAP.get(channel, index)
                field = json.dumps([task_id, index])
                operation = pipe.hset if index < 0 else pipe.hsetnx
                operation(key, field, self._encode((task_id, channel, value)))
            pipe.execute()

    def list(
        self, config: RunnableConfig | None, *, filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None, limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        keys = [self._key(config)] if config else [
            value.decode().removesuffix(":index")
            for value in self.client.scan_iter(match=f"{self.prefix}:*:index")
        ]
        remaining = limit
        for key in keys:
            for raw in cast(list[bytes], self.client.zrevrange(key + ":index", 0, -1)):
                checkpoint_id = raw.decode()
                if before and checkpoint_id >= (get_checkpoint_id(before) or ""):
                    continue
                if config and get_checkpoint_id(config) not in (None, checkpoint_id):
                    continue
                stored = self.client.hget(key, checkpoint_id)
                if stored is None:
                    continue
                saved = self._decode(stored)
                item = self.get_tuple(saved["config"])
                if item is None or (filter and any(
                    item.metadata.get(k) != v for k, v in filter.items()
                )):
                    continue
                if remaining is not None:
                    if remaining <= 0:
                        return
                    remaining -= 1
                yield item

    def delete_thread(self, thread_id: str) -> None:
        index = self.prefix + ":threads:" + thread_id
        for raw in cast(set[bytes], self.client.smembers(index)):
            key = raw.decode()
            write_keys = [value for value in self.client.scan_iter(match=key + ":writes:*")]
            self.client.delete(key, key + ":index", *write_keys)
        self.client.delete(index)

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return await asyncio.to_thread(self.get_tuple, config)

    async def aput(
        self, config: RunnableConfig, checkpoint: Checkpoint,
        metadata: CheckpointMetadata, new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return await asyncio.to_thread(self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self, config: RunnableConfig, writes: Sequence[tuple[str, Any]],
        task_id: str, task_path: str = "",
    ) -> None:
        await asyncio.to_thread(self.put_writes, config, writes, task_id, task_path)

    async def alist(
        self, config: RunnableConfig | None, *, filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None, limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        items = await asyncio.to_thread(
            lambda: list(self.list(config, filter=filter, before=before, limit=limit))
        )
        for item in items:
            yield item

    async def adelete_thread(self, thread_id: str) -> None:
        await asyncio.to_thread(self.delete_thread, thread_id)
