"""The app's real startup and shutdown, run offline.

The endpoint tests replace the client dependency, so they never run the lifespan.
This one does, with only the network swapped for the fake.
"""

import httpx
from fastapi.testclient import TestClient

from app.main import app
from tests.fakes import USERS, FakeDummyJson


def test_startup_builds_the_upstream_client_from_settings(monkeypatch):
    upstream = FakeDummyJson(USERS)
    created: list[httpx.Client] = []
    real_client = httpx.Client

    def client_on_fake_transport(**kwargs) -> httpx.Client:
        client = real_client(transport=httpx.MockTransport(upstream.handle), **kwargs)
        created.append(client)
        return client

    monkeypatch.setattr(httpx, "Client", client_on_fake_transport)
    monkeypatch.setenv("UPSTREAM_BASE_URL", "https://upstream.test/api")
    monkeypatch.setenv("UPSTREAM_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("UPSTREAM_PAGE_SIZE", "2")

    # Used as a context manager, so the lifespan runs: startup on entry, shutdown on exit.
    with TestClient(app) as client:
        response = client.get("/users")

    assert response.status_code == 200
    assert response.json()["count"] == 5
    assert str(upstream.requests[0].url).startswith("https://upstream.test/api/users?")
    assert upstream.skips == [0, 2, 4]

    (http,) = created
    assert http.timeout == httpx.Timeout(2.5)
    assert http.is_closed
