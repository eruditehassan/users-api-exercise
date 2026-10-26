"""Fixtures: a fake DummyJSON and an API test client wired to it."""

from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.dummyjson import DummyJsonClient
from app.main import app, get_dummyjson
from tests.fakes import USERS, FakeDummyJson

# Small, so that the five test users span three pages.
PAGE_SIZE = 2


@pytest.fixture
def upstream() -> FakeDummyJson:
    """The fake upstream. Tests change its users, total or overrides before calling the API."""
    return FakeDummyJson(USERS)


@pytest.fixture
def api(upstream: FakeDummyJson) -> Iterator[TestClient]:
    """A client for our API whose upstream calls go to the fake instead of the network."""
    http = httpx.Client(
        base_url="https://dummyjson.test", transport=httpx.MockTransport(upstream.handle)
    )
    dummyjson = DummyJsonClient(http, page_size=PAGE_SIZE)
    app.dependency_overrides[get_dummyjson] = lambda: dummyjson
    try:
        # Not used as a context manager, so the app's lifespan (the real HTTP client) never starts.
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        http.close()
