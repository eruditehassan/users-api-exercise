"""An in-memory stand-in for the DummyJSON users API, used through httpx.MockTransport."""

import httpx


def upstream_user(user_id: int, first_name: str, last_name: str) -> dict:
    """A DummyJSON-style record, including fields the API must not return."""
    return {
        "id": user_id,
        "firstName": first_name,
        "lastName": last_name,
        "email": f"{first_name}.{last_name}@x.dummyjson.com".lower(),
        "phone": f"+44 7700 900{user_id:03d}",
        "age": 30,
        "password": "not-for-consumers",
        "ssn": "000-00-0000",
        "address": {"city": "Cardiff", "postalCode": "CF10 3AT"},
    }


# With a page size of 2 these span three pages; Samantha appears only on the last one.
USERS = [
    upstream_user(1, "Emily", "Johnson"),
    upstream_user(2, "Michael", "Williams"),
    upstream_user(3, "Emily", "Smith"),
    upstream_user(4, "James", "Davis"),
    upstream_user(5, "Samantha", "Martinez"),
]


def page_response(users: list[dict], total: int, skip: int = 0) -> httpx.Response:
    """A successful DummyJSON page with the given contents."""
    return httpx.Response(
        200, json={"users": users, "total": total, "skip": skip, "limit": len(users)}
    )


def without(record: dict, field: str) -> dict:
    """A copy of the record with one field removed."""
    return {key: value for key, value in record.items() if key != field}


class FakeDummyJson:
    """Serves DummyJSON-style pages from a list of records and keeps every request it receives.

    `overrides` simulates faults: it maps a request number (counting from 1) to a
    prepared response to return instead, or to an exception to raise.
    """

    def __init__(self, users: list[dict], total: int | None = None) -> None:
        self.users = users
        self.total = len(users) if total is None else total
        self.overrides: dict[int, httpx.Response | Exception] = {}
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        override = self.overrides.get(len(self.requests))
        if isinstance(override, Exception):
            raise override
        if override is not None:
            return override

        skip = int(request.url.params["skip"])
        limit = int(request.url.params["limit"])
        return page_response(self.users[skip : skip + limit], self.total, skip)

    @property
    def skips(self) -> list[int]:
        """The skip value of each request, in order."""
        return [int(request.url.params["skip"]) for request in self.requests]
