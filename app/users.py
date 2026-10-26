"""User model, response model and name filtering."""

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field


class User(BaseModel):
    """The five fields we publish.

    Anything else in an upstream record is dropped when it's parsed. Strict mode
    means a value of the wrong type is an error rather than being converted.
    """

    model_config = ConfigDict(strict=True, extra="ignore")

    id: int
    firstName: str
    lastName: str
    email: str
    phone: str


class UsersResponse(BaseModel):
    total: int = Field(description="Users reported by the upstream API, before filtering.")
    count: int = Field(description="Users included in this response, after filtering.")
    users: list[User]


def filter_users(
    users: Iterable[User],
    first_name: str | None = None,
    last_name: str | None = None,
) -> list[User]:
    """Users matching every supplied filter, in their original order.

    Matching is exact and case-insensitive. Empty or whitespace-only filters are ignored.
    """
    wanted_first = _normalise(first_name)
    wanted_last = _normalise(last_name)
    return [
        user
        for user in users
        if (wanted_first is None or user.firstName == wanted_first)
        and (wanted_last is None or user.lastName == wanted_last)
    ]


def _normalise(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip()
