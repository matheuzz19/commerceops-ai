from dataclasses import dataclass

from fastapi import Header, HTTPException, status


@dataclass(frozen=True)
class RequestContext:
    tenant_id: str
    user_id: str


async def get_request_context(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
) -> RequestContext:
    if not x_tenant_id or not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-ID and X-User-ID headers are required.",
        )
    return RequestContext(tenant_id=x_tenant_id, user_id=x_user_id)
