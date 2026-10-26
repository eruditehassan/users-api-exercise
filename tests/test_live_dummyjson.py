"""Contract checks against the real DummyJSON API.

These confirm the upstream still behaves as the offline tests assume (fields,
select and paging). They need network access, so they are excluded from the
default run. Run them with: pytest -m live
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.live

PUBLISHED_FIELDS = {"id", "firstName", "lastName", "email", "phone"}


@pytest.fixture(scope="module")
def live_api() -> Iterator[TestClient]:
    # Used as a context manager, so the app's lifespan creates the real upstream client.
    with TestClient(app) as client:
        yield client


def test_returns_every_upstream_user_with_published_fields_only(live_api):
    response = live_api.get("/users")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] > 0
    assert body["count"] == body["total"] == len(body["users"])
    assert len({user["id"] for user in body["users"]}) == body["total"]
    assert all(set(user) == PUBLISHED_FIELDS for user in body["users"])


def test_filters_real_data_by_both_names(live_api):
    first_user = live_api.get("/users").json()["users"][0]

    body = live_api.get(
        "/users",
        params={
            "firstName": first_user["firstName"].upper(),
            "lastName": first_user["lastName"].lower(),
        },
    ).json()

    assert first_user in body["users"]
    assert body["count"] == len(body["users"])
    for user in body["users"]:
        assert user["firstName"].casefold() == first_user["firstName"].casefold()
        assert user["lastName"].casefold() == first_user["lastName"].casefold()
