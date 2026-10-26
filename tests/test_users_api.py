"""Behaviour of GET /users, with DummyJSON replaced by an in-memory fake."""

import logging

import httpx
import pytest

from tests.fakes import USERS, page_response, without

PUBLISHED_FIELDS = {"id", "firstName", "lastName", "email", "phone"}
UNEXPECTED = "Upstream user service returned an unexpected response"


# Retrieval and transformation


def test_returns_every_user_across_pages(api, upstream):
    response = api.get("/users")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert body["count"] == 5
    assert [user["id"] for user in body["users"]] == [1, 2, 3, 4, 5]
    assert upstream.skips == [0, 2, 4]


def test_follows_pages_shorter_than_requested(api, upstream):
    # The upstream sends one user although two were requested; the next page starts after it.
    upstream.overrides[1] = page_response(USERS[:1], total=5)

    body = api.get("/users").json()

    assert [user["id"] for user in body["users"]] == [1, 2, 3, 4, 5]
    assert upstream.skips == [0, 1, 3]


def test_asks_upstream_for_the_published_fields_only(api, upstream):
    api.get("/users")

    params = upstream.requests[0].url.params
    assert params["select"] == "firstName,lastName,email,phone"
    assert params["limit"] == "2"


def test_returns_only_the_published_fields(api):
    users = api.get("/users").json()["users"]

    assert all(set(user) == PUBLISHED_FIELDS for user in users)
    assert users[0] == {
        "id": 1,
        "firstName": "Emily",
        "lastName": "Johnson",
        "email": "emily.johnson@x.dummyjson.com",
        "phone": "+44 7700 900001",
    }


def test_empty_upstream_dataset_is_a_normal_response(api, upstream):
    upstream.users, upstream.total = [], 0

    response = api.get("/users")

    assert response.status_code == 200
    assert response.json() == {"total": 0, "count": 0, "users": []}


# Filtering


def test_first_name_filter_ignores_case_and_covers_every_page(api):
    body = api.get("/users", params={"firstName": "sAMANTHA"}).json()

    assert body["total"] == 5
    assert body["count"] == 1
    assert body["users"][0]["id"] == 5


def test_last_name_filter(api):
    body = api.get("/users", params={"lastName": "smith"}).json()

    assert [user["id"] for user in body["users"]] == [3]


def test_both_filters_must_match(api):
    body = api.get("/users", params={"firstName": "Emily", "lastName": "Smith"}).json()

    # Emily Johnson matches the first name only, so she is excluded.
    assert [user["id"] for user in body["users"]] == [3]
    assert body["count"] == 1


def test_no_match_returns_an_empty_list(api):
    response = api.get("/users", params={"firstName": "Nobody"})

    assert response.status_code == 200
    assert response.json() == {"total": 5, "count": 0, "users": []}


@pytest.mark.parametrize("blank", ["", "   "], ids=["empty", "whitespace"])
def test_blank_filter_is_treated_as_not_supplied(api, blank):
    body = api.get("/users", params={"firstName": blank}).json()

    assert body["count"] == 5


def test_names_must_match_exactly(api):
    assert api.get("/users", params={"firstName": "Em"}).json()["count"] == 0


def test_unknown_query_parameters_are_ignored(api):
    assert api.get("/users", params={"unknown": "value"}).json()["count"] == 5


# Upstream failures


def test_upstream_error_after_an_earlier_page_returns_502(api, upstream):
    upstream.overrides[2] = httpx.Response(500, json={"message": "Internal error"})

    response = api.get("/users")

    assert response.status_code == 502
    assert response.json() == {"detail": "Upstream user service returned HTTP 500"}


def test_upstream_timeout_returns_504(api, upstream):
    upstream.overrides[1] = httpx.ReadTimeout("read timed out")

    response = api.get("/users")

    assert response.status_code == 504
    assert response.json() == {"detail": "Upstream user service timed out"}


def test_unreachable_upstream_returns_502(api, upstream):
    upstream.overrides[1] = httpx.ConnectError("connection refused")

    response = api.get("/users")

    assert response.status_code == 502
    assert response.json() == {"detail": "Could not reach upstream user service"}


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(httpx.Response(200, text="<html>Maintenance</html>"), id="body-not-json"),
        pytest.param(httpx.Response(200, json={"total": 5}), id="users-missing"),
        pytest.param(page_response([without(USERS[0], "email")], total=5), id="record-missing-email"),
        pytest.param(page_response([{**USERS[0], "id": "1"}], total=5), id="id-is-a-string"),
        pytest.param(page_response([USERS[0]], total=0), id="users-despite-zero-total"),
    ],
)
def test_unexpected_upstream_response_returns_502(api, upstream, reply):
    upstream.overrides[1] = reply

    response = api.get("/users")

    assert response.status_code == 502
    assert response.json()["detail"].startswith(UNEXPECTED)
    assert "users" not in response.json()


def test_upstream_failure_is_logged_without_user_data(api, upstream, caplog):
    upstream.overrides[2] = httpx.Response(503)

    with caplog.at_level(logging.WARNING, logger="app.main"):
        api.get("/users", params={"firstName": "Emily"})

    assert "GET /users failed with 502: Upstream user service returned HTTP 503" in caplog.text
    assert "Emily" not in caplog.text


# Paging consistency: anything that would make the result incomplete or doubtful is a 502.


def test_empty_page_before_all_users_arrive_returns_502(api, upstream):
    upstream.overrides[2] = page_response([], total=5, skip=2)

    response = api.get("/users")

    assert response.status_code == 502
    assert response.json() == {"detail": f"{UNEXPECTED}: empty page before all users were received"}


def test_repeated_page_returns_502(api, upstream):
    # The upstream ignores skip and sends the first page again.
    upstream.overrides[2] = page_response(USERS[:2], total=5)

    response = api.get("/users")

    assert response.status_code == 502
    assert response.json() == {"detail": f"{UNEXPECTED}: user id repeated across pages"}


def test_total_changing_between_pages_returns_502(api, upstream):
    upstream.overrides[2] = page_response(USERS[2:4], total=6, skip=2)

    response = api.get("/users")

    assert response.status_code == 502
    assert response.json() == {"detail": f"{UNEXPECTED}: total changed while paging"}


def test_more_users_than_total_returns_502(api, upstream):
    # The upstream reports three users but the second page brings the count to four.
    upstream.total = 3

    response = api.get("/users")

    assert response.status_code == 502
    assert response.json() == {"detail": f"{UNEXPECTED}: received more users than total"}
