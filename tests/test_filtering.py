"""The name-matching rules on their own, without HTTP."""

from app.users import User, filter_users


def person(user_id: int, first_name: str, last_name: str) -> User:
    return User(
        id=user_id,
        firstName=first_name,
        lastName=last_name,
        email=f"user{user_id}@example.com",
        phone="+44 7700 900000",
    )


PEOPLE = [
    person(1, "Emily", "Johnson"),
    person(2, "Emily", "Smith"),
    person(3, "Jürgen", "Straße"),
]


def test_no_filters_returns_everyone_in_order():
    assert filter_users(PEOPLE) == PEOPLE


def test_matching_ignores_case_and_surrounding_whitespace():
    assert [user.id for user in filter_users(PEOPLE, first_name="  eMILY ")] == [1, 2]


def test_both_filters_must_match():
    assert [user.id for user in filter_users(PEOPLE, "emily", "smith")] == [2]


def test_case_folding_handles_non_ascii_names():
    assert [user.id for user in filter_users(PEOPLE, last_name="STRASSE")] == [3]


def test_partial_names_do_not_match():
    assert filter_users(PEOPLE, first_name="Emil") == []
