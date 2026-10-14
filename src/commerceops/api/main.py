import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST
from redis.exceptions import RedisError

from commerceops.api.redis_runtime import RedisConversationRuntime
from commerceops.api.routes.health import router as health_router
from commerceops.api.routes.messages import router as messages_router
from commerceops.api.runtime import get_conversation_runtime
from commerceops.gateway.storage import SessionConflict
from commerceops.observability.http import ObservationMiddleware
from commerceops.observability.logging import configure_logging
from commerceops.observability.metrics import render_metrics
from commerceops.observability.tracing import tracing_client


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    factory = app.dependency_overrides.get(get_conversation_runtime, get_conversation_runtime)
    runtime = factory()
    worker = None
    if isinstance(runtime, RedisConversationRuntime):
        worker = asyncio.create_task(runtime.worker_loop())
    try:
        yield
    finally:
        if worker is not None:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
            await runtime.close()
        client = tracing_client()
        if client is not None:
            await asyncio.to_thread(client.flush, timeout=10)


app = FastAPI(title="CommerceOps AI", version="0.1.0", lifespan=lifespan)
app.add_middleware(ObservationMiddleware)
app.include_router(health_router)
app.include_router(messages_router)


@app.exception_handler(SessionConflict)
async def session_conflict_handler(request: Request, error: SessionConflict) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={
            "detail": {
                "code": error.code,
                "message": error.message,
            }
        },
    )


@app.exception_handler(RedisError)
async def state_store_error_handler(request: Request, error: RedisError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "detail": {
                "code": "STATE_STORE_UNAVAILABLE",
                "message": "The conversation state store is unavailable.",
            }
        },
    )


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics() -> Response:
    return Response(content=render_metrics(), headers={"Content-Type": CONTENT_TYPE_LATEST})
