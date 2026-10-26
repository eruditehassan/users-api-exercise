"""DummyJSON users client: paging, validation and upstream errors."""

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.users import User

# DummyJSON always includes "id", so only the other fields need selecting.
SELECTED_FIELDS = "firstName,lastName,email,phone"


class UpstreamError(Exception):
    """The upstream failed or sent something we can't rely on.

    The message goes back to the consumer, so it never includes the upstream
    body or the values that failed validation.
    """


class UpstreamTimeout(UpstreamError):
    """The upstream didn't respond within the timeout."""


class _Page(BaseModel):
    """One page of GET /users. skip and limit are ignored; see fetch_all_users."""

    model_config = ConfigDict(strict=True, extra="ignore")

    users: list[User]
    total: int = Field(ge=0)


class DummyJsonClient:
    def __init__(self, http: httpx.Client, page_size: int = 100) -> None:
        if page_size < 1:
            raise ValueError("page_size must be at least 1")
        self._http = http
        self._page_size = page_size

    def fetch_all_users(self) -> tuple[int, list[User]]:
        """Return (total, users), or raise UpstreamError.

        Each page is checked before asking for the next, so this either returns
        every user or fails. It never returns a partial list.
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
            # Has to come before RequestError, which is its parent class.
            raise UpstreamTimeout("Upstream user service timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(
                f"Upstream user service returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise UpstreamError("Could not reach upstream user service") from exc

        try:
            # Covers a body that isn't JSON, the wrong shape and wrong field types.
            return _Page.model_validate_json(response.content)
        except ValidationError as exc:
            raise _unexpected() from exc


def _unexpected(reason: str | None = None) -> UpstreamError:
    message = "Upstream user service returned an unexpected response"
    return UpstreamError(f"{message}: {reason}" if reason else message)
