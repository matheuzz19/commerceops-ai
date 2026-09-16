"""Application boundary for checkpointed supervisor execution."""

from functools import lru_cache
from typing import Any
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from commerceops.agents.supervisor.graph import create_supervisor_graph
from commerceops.api.schemas import MessageRequest, MessageResponse
from commerceops.graph.checkpoints import PendingCheckpoint, PendingCheckpointStore


class ConversationRuntime:
    def __init__(
        self,
        graph: Any | None = None,
        pending: PendingCheckpointStore | None = None,
    ) -> None:
        self.graph = graph or create_supervisor_graph(checkpointer=InMemorySaver())
        self.pending = pending or PendingCheckpointStore()

    async def submit(
        self, request: MessageRequest, tenant_id: str, user_id: str
    ) -> MessageResponse:
        trace_id = str(uuid4())
        checkpoint_id = str(uuid4())
        config = {"configurable": {"thread_id": checkpoint_id}}
        result = await self.graph.ainvoke(
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "session_id": request.session_id,
                "message_id": request.message_id,
                "content": request.content,
                "content_type": request.content_type,
            },
            config=config,
        )
        return self._response(
            result, trace_id, checkpoint_id, tenant_id, user_id, config
        )

    async def resume(
        self,
        checkpoint_id: str,
        tenant_id: str,
        user_id: str,
        *,
        approved: bool,
    ) -> MessageResponse | None:
        checkpoint = self.pending.get(checkpoint_id)
        if checkpoint is None:
            return None
        if checkpoint.tenant_id != tenant_id or checkpoint.user_id != user_id:
            return None

        trace_id = str(uuid4())
        result = await self.graph.ainvoke(
            Command(resume={"approved": approved}), config=checkpoint.config
        )
        response = self._response(
            result,
            trace_id,
            checkpoint_id,
            tenant_id,
            user_id,
            checkpoint.config,
        )
        if response.status != "requires_confirmation":
            self.pending.remove(checkpoint_id)
        return response

    def _response(
        self,
        result: dict[str, Any],
        trace_id: str,
        checkpoint_id: str,
        tenant_id: str,
        user_id: str,
        config: dict[str, Any],
    ) -> MessageResponse:
        interrupts = result.get("__interrupt__", ())
        if interrupts:
            confirmation = interrupts[0].value
            self.pending.put(
                PendingCheckpoint(checkpoint_id, tenant_id, user_id, config)
            )
            return MessageResponse(
                status="requires_confirmation",
                response=str(confirmation.get("message", "Approval is required.")),
                checkpoint_id=checkpoint_id,
                trace_id=trace_id,
                confirmation=confirmation,
            )

        error = result.get("error")
        return MessageResponse(
            status="failed" if error and error != "ROUTER_CLASSIFICATION_FAILED" else "completed",
            response=result.get("final_response"),
            checkpoint_id=None,
            trace_id=trace_id,
        )


@lru_cache
def get_conversation_runtime() -> ConversationRuntime:
    return ConversationRuntime()
