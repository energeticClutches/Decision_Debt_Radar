from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_reports_ok_and_param_versions():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["ddi_params_version"] == "ddi_params_v0.1"
    assert body["nbe_params_version"] == "nbe_params_v0.1"
