"""Message intake, trusted approvals and tenant-scoped session inspection."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status

from commerceops.api.runtime import ConversationRuntime, get_conversation_runtime
from commerceops.api.schemas import MessageRequest, MessageResponse, SessionStateResponse

router = APIRouter()


def trusted_identity(
    tenant_id: Annotated[str, Header(alias="X-Tenant-ID", min_length=1)],
    user_id: Annotated[str, Header(alias="X-User-ID", min_length=1)],
) -> tuple[str, str]:
    return tenant_id, user_id


@router.post("/messages", response_model=MessageResponse)
async def submit_message(
    request: MessageRequest,
    identity: Annotated[tuple[str, str], Depends(trusted_identity)],
    runtime: Annotated[ConversationRuntime, Depends(get_conversation_runtime)],
) -> MessageResponse:
    tenant_id, user_id = identity
    return await runtime.submit(request, tenant_id, user_id)


@router.post("/confirmations/{checkpoint_id}/approve", response_model=MessageResponse)
async def approve_confirmation(
    checkpoint_id: str,
    identity: Annotated[tuple[str, str], Depends(trusted_identity)],
    runtime: Annotated[ConversationRuntime, Depends(get_conversation_runtime)],
) -> MessageResponse:
    tenant_id, user_id = identity
    response = await runtime.resume(
        checkpoint_id, tenant_id, user_id, approved=True
    )
    if response is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Checkpoint not found.")
    return response


@router.post("/confirmations/{checkpoint_id}/reject", response_model=MessageResponse)
async def reject_confirmation(
    checkpoint_id: str,
    identity: Annotated[tuple[str, str], Depends(trusted_identity)],
    runtime: Annotated[ConversationRuntime, Depends(get_conversation_runtime)],
) -> MessageResponse:
    tenant_id, user_id = identity
    response = await runtime.resume(
        checkpoint_id, tenant_id, user_id, approved=False
    )
    if response is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Checkpoint not found.")
    return response


@router.get("/sessions/{session_id}/state", response_model=SessionStateResponse)
async def inspect_session(
    session_id: str,
    identity: Annotated[tuple[str, str], Depends(trusted_identity)],
    runtime: Annotated[ConversationRuntime, Depends(get_conversation_runtime)],
) -> SessionStateResponse:
    tenant_id, user_id = identity
    response = await runtime.session_state(session_id, tenant_id, user_id)
    if response is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    return response
