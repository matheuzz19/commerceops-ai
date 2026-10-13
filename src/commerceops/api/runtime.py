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
        checkpoint = self.pending.claim(checkpoint_id, tenant_id, user_id)
        if checkpoint is None:
            return None
        trace_id = str(uuid4())
        # Every exposed interrupt receives an explicit, ID-scoped decision.
        resume_values = {
            interrupt_id: {"approved": approved} for interrupt_id in checkpoint.interrupt_ids
        }
        try:
            result = await self.graph.ainvoke(
                Command(resume=resume_values), config=checkpoint.config
            )
        except Exception:
            # The write may have reached the service. Never replay an uncertain write.
            return MessageResponse(
                status="failed", response="The approval could not be completed safely. "
                "Please inspect the operation before submitting another request.",
                checkpoint_id=None, trace_id=trace_id,
            )
        return self._response(
            result, trace_id, str(uuid4()), tenant_id, user_id, checkpoint.config
        )

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
            entries = [
                {"interrupt_id": item.id, "payload": item.value} for item in interrupts
            ]
            if len(entries) == 1:
                confirmation = dict(interrupts[0].value)
                confirmation["interrupt_id"] = interrupts[0].id
            else:
                confirmation = {
                    "message": "Please approve or reject all pending actions.",
                    "interrupts": entries,
                }
            self.pending.put(PendingCheckpoint(
                checkpoint_id, tenant_id, user_id, config,
                tuple(item.id for item in interrupts),
            ))
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
