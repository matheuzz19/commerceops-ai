"""M6 in-process checkpoint ownership for graph interrupt and resume.

Redis-backed persistence is deliberately deferred to M7. M6 keeps checkpoint
identity and tenant ownership outside model-controlled graph state.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PendingCheckpoint:
    checkpoint_id: str
    tenant_id: str
    user_id: str
    config: dict[str, Any]


class PendingCheckpointStore:
    def __init__(self) -> None:
        self._items: dict[str, PendingCheckpoint] = {}

    def put(self, checkpoint: PendingCheckpoint) -> None:
        self._items[checkpoint.checkpoint_id] = checkpoint

    def get(self, checkpoint_id: str) -> PendingCheckpoint | None:
        return self._items.get(checkpoint_id)

    def remove(self, checkpoint_id: str) -> None:
        self._items.pop(checkpoint_id, None)
