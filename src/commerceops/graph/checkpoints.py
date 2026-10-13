"""M6 in-process checkpoint ownership for graph interrupt and resume.

Redis-backed persistence is deliberately deferred to M7. M6 keeps checkpoint
identity and tenant ownership outside model-controlled graph state.
"""

from dataclasses import dataclass
from threading import Lock
from typing import Any


@dataclass(frozen=True)
class PendingCheckpoint:
    checkpoint_id: str
    tenant_id: str
    user_id: str
    config: dict[str, Any]
    interrupt_ids: tuple[str, ...] = ()


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
