"""Trusted approval ownership, with in-memory and atomic Redis stores."""

import json
from dataclasses import asdict, dataclass
from threading import Lock
from typing import Any

from redis import Redis


@dataclass(frozen=True)
class PendingCheckpoint:
    checkpoint_id: str
    tenant_id: str
    user_id: str
    config: dict[str, Any]
    interrupt_ids: tuple[str, ...] = ()
    session_id: str | None = None


class PendingCheckpointStore:
    def __init__(self) -> None:
        self._items: dict[str, PendingCheckpoint] = {}
        self._lock = Lock()

    def put(self, checkpoint: PendingCheckpoint) -> None:
        with self._lock:
            self._items[checkpoint.checkpoint_id] = checkpoint

    def get(self, checkpoint_id: str) -> PendingCheckpoint | None:
        with self._lock:
            return self._items.get(checkpoint_id)

    def remove(self, checkpoint_id: str) -> None:
        with self._lock:
            self._items.pop(checkpoint_id, None)

    def claim(
        self, checkpoint_id: str, tenant_id: str, user_id: str
    ) -> PendingCheckpoint | None:
        """Consume one approval atomically; unauthorized callers cannot consume it."""
        with self._lock:
            checkpoint = self._items.get(checkpoint_id)
            if checkpoint is None:
                return None
            if checkpoint.tenant_id != tenant_id or checkpoint.user_id != user_id:
                return None
            return self._items.pop(checkpoint_id)


class RedisPendingCheckpointStore(PendingCheckpointStore):
    def __init__(self, client: Redis, prefix: str = "commerceops:pending") -> None:
        self.client = client
        self.prefix = prefix

    def _key(self, checkpoint_id: str) -> str:
        return f"{self.prefix}:{checkpoint_id}"

    def put(self, checkpoint: PendingCheckpoint) -> None:
        self.client.set(self._key(checkpoint.checkpoint_id), json.dumps(asdict(checkpoint)))

    def get(self, checkpoint_id: str) -> PendingCheckpoint | None:
        raw = self.client.get(self._key(checkpoint_id))
        return self._parse(raw) if raw else None

    def remove(self, checkpoint_id: str) -> None:
        self.client.delete(self._key(checkpoint_id))

    @staticmethod
    def _parse(raw: bytes | str) -> PendingCheckpoint:
        values = json.loads(raw)
        values["interrupt_ids"] = tuple(values["interrupt_ids"])
        return PendingCheckpoint(**values)

    def claim(
        self, checkpoint_id: str, tenant_id: str, user_id: str
    ) -> PendingCheckpoint | None:
        raw = self.client.eval(
            """
            local raw = redis.call('GET', KEYS[1])
            if not raw then return false end
            local item = cjson.decode(raw)
            if item.tenant_id ~= ARGV[1] or item.user_id ~= ARGV[2] then return false end
            redis.call('DEL', KEYS[1])
            return raw
            """,
            1, self._key(checkpoint_id), tenant_id, user_id,
        )
        return self._parse(raw) if raw else None
