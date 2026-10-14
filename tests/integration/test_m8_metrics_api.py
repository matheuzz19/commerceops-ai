from fastapi.testclient import TestClient

from commerceops.api.main import app
from commerceops.api.runtime import ConversationRuntime, get_conversation_runtime


def test_metrics_endpoint_and_unmatched_paths_do_not_expose_identity() -> None:
    app.dependency_overrides[get_conversation_runtime] = lambda: ConversationRuntime(graph=object())
    try:
        with TestClient(app) as client:
            missing = client.get("/not-found/private-session-id")
            assert missing.status_code == 404
            assert "x-request-id" in missing.headers
            response = client.get("/metrics")
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/plain")
            assert 'route="unmatched"' in response.text
            assert "private-session-id" not in response.text
            assert "tenant_id=" not in response.text
    finally:
        app.dependency_overrides.clear()
