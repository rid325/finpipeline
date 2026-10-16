from fastapi.testclient import TestClient


def test_health_is_a_single_cheap_connection_check(monkeypatch):
    import src.api as api

    class Connection:
        closed = False

        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr(api, "get_connection", lambda: connection)
    with TestClient(api.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "database": "connected"}
    assert connection.closed is True
