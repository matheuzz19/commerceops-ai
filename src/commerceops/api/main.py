from fastapi import FastAPI

from commerceops.api.routes.health import router as health_router
from commerceops.api.routes.messages import router as messages_router

app = FastAPI(title="CommerceOps AI", version="0.1.0")
app.include_router(health_router)
app.include_router(messages_router)
