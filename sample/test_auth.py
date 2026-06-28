"""Pytest unit tests for sample/auth.py.

These document the *current* behaviour of ``login`` — including its sloppy
parts (plaintext password match, implicit ``None`` on failure). The crew's
reviewer agent should flag those; these tests just pin down what the code does
today so a refactor doesn't change behaviour silently.

Run them:
    pytest sample/test_auth.py -v
"""

import pytest

from auth import login


@pytest.fixture
def users():
    return [
        {"name": "alice", "password": "wonderland"},
        {"name": "bob", "password": "builder"},
    ]


def test_successful_login_returns_user(users):
    result = login(users, "alice", "wonderland")
    assert result == {"name": "alice", "password": "wonderland"}


def test_returns_the_actual_user_object(users):
    # The matched user is the same object from the list, not a copy.
    result = login(users, "bob", "builder")
    assert result is users[1]


def test_wrong_password_returns_none(users):
    assert login(users, "alice", "nope") is None


def test_unknown_user_returns_none(users):
    assert login(users, "carol", "whatever") is None


def test_empty_user_list_returns_none():
    assert login([], "alice", "wonderland") is None


def test_case_sensitive_name(users):
    # Matching is exact/case-sensitive.
    assert login(users, "Alice", "wonderland") is None


def test_first_match_wins():
    dupes = [
        {"name": "dup", "password": "pw", "id": 1},
        {"name": "dup", "password": "pw", "id": 2},
    ]
    assert login(dupes, "dup", "pw")["id"] == 1


def test_missing_keys_raise_keyerror():
    # A user dict without the expected keys blows up — no defensive handling.
    with pytest.raises(KeyError):
        login([{"username": "x"}], "x", "y")
