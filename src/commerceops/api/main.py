import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError

from commerceops.api.redis_runtime import RedisConversationRuntime
from commerceops.api.routes.health import router as health_router
from commerceops.api.routes.messages import router as messages_router
from commerceops.api.runtime import get_conversation_runtime
from commerceops.gateway.storage import SessionConflict


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
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


app = FastAPI(title="CommerceOps AI", version="0.1.0", lifespan=lifespan)
app.include_router(health_router)
app.include_router(messages_router)


@app.exception_handler(SessionConflict)
async def session_conflict_handler(request: Request, error: SessionConflict) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content={"detail": {
        "code": error.code, "message": error.message,
    }})


@app.exception_handler(RedisError)
async def state_store_error_handler(request: Request, error: RedisError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": {
        "code": "STATE_STORE_UNAVAILABLE",
        "message": "The conversation state store is unavailable.",
    }})
