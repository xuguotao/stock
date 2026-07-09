from __future__ import annotations

import inspect

from fastapi.testclient import TestClient

from src.web.backend.app import create_app


def test_health_endpoint_is_async_so_threadpool_saturation_does_not_block_it(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "jobs.json")
    route = next(route for route in app.routes if getattr(route, "path", None) == "/api/health")

    assert inspect.iscoroutinefunction(route.endpoint)

    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
