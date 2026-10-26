"""The published user record, the response contract and the name filters."""

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field


class User(BaseModel):
    """The five fields this service publishes for each user.

    Upstream records carry many more fields. Anything not declared here is
    dropped when a record is parsed, so it can never reach a consumer.
    Strict mode rejects a value of the wrong type instead of converting it,
    which means upstream values are either passed through unchanged or the
    request fails.
    """

    model_config = ConfigDict(strict=True, extra="ignore")

    id: int
    firstName: str
    lastName: str
    email: str
    phone: str


class UsersResponse(BaseModel):
    """Body of every response that contains user data."""

    total: int = Field(description="Users reported by the upstream API, before filtering.")
    count: int = Field(description="Users included in this response, after filtering.")
    users: list[User]


def filter_users(
    users: Iterable[User],
    first_name: str | None = None,
    last_name: str | None = None,
) -> list[User]:
    """Return the users whose names match every supplied filter, in their original order.

    Matching is exact and case-insensitive. A filter that is missing, empty or
    only whitespace counts as not supplied.
    """
    wanted_first = _normalise(first_name)
    wanted_last = _normalise(last_name)
    return [
        user
        for user in users
        if (wanted_first is None or user.firstName.casefold() == wanted_first)
        and (wanted_last is None or user.lastName.casefold() == wanted_last)
    ]


def _normalise(value: str | None) -> str | None:
    """Prepare a filter value for comparison, or return None when there is nothing to match."""
    if value is None or not value.strip():
        return None
    # casefold() rather than lower(): it also handles cases such as "Straße" and "STRASSE".
    return value.strip().casefold()
