"""Client for the DummyJSON users API: paging, validation and failure handling."""

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.users import User

# DummyJSON always includes "id", so only the other published fields are selected.
SELECTED_FIELDS = "firstName,lastName,email,phone"


class UpstreamError(Exception):
    """The upstream API failed, or returned data this service cannot rely on.

    Messages are written for API consumers. They never include upstream
    response bodies or the values that failed validation.
    """


class UpstreamTimeout(UpstreamError):
    """The upstream API did not respond within the configured timeout."""


class _Page(BaseModel):
    """One page of the upstream /users response. Other keys, such as skip and limit, are ignored."""

    model_config = ConfigDict(strict=True, extra="ignore")

    users: list[User]
    total: int = Field(ge=0)


class DummyJsonClient:
    """Retrieves the complete user list from DummyJSON, one page at a time."""

    def __init__(self, http: httpx.Client, page_size: int = 100) -> None:
        if page_size < 1:
            raise ValueError("page_size must be at least 1")
        self._http = http
        self._page_size = page_size

    def fetch_all_users(self) -> tuple[int, list[User]]:
        """Return the upstream total and every user, or raise UpstreamError.

        Each page is checked before the next one is requested, so the result is
        either complete or an error. A partial list is never returned.
        """
        users: list[User] = []
        seen_ids: set[int] = set()
        total: int | None = None

        while True:
            page = self._fetch_page(skip=len(users))

            if total is None:
                total = page.total
            elif page.total != total:
                raise _unexpected("total changed while paging")

            for user in page.users:
                if user.id in seen_ids:
                    raise _unexpected("user id repeated across pages")
                seen_ids.add(user.id)
                users.append(user)

            if len(users) > total:
                raise _unexpected("received more users than total")
            if len(users) == total:
                return total, users
            if not page.users:
                raise _unexpected("empty page before all users were received")

    def _fetch_page(self, skip: int) -> _Page:
        params = {"limit": self._page_size, "skip": skip, "select": SELECTED_FIELDS}
        try:
            response = self._http.get("/users", params=params)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            # Caught before RequestError, which is its parent class.
            raise UpstreamTimeout("Upstream user service timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(
                f"Upstream user service returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise UpstreamError("Could not reach upstream user service") from exc

        try:
            # One ValidationError covers a body that is not JSON, the wrong shape and wrong types.
            return _Page.model_validate_json(response.content)
        except ValidationError as exc:
            raise _unexpected() from exc


def _unexpected(reason: str | None = None) -> UpstreamError:
    message = "Upstream user service returned an unexpected response"
    return UpstreamError(f"{message}: {reason}" if reason else message)
