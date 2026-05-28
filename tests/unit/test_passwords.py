"""argon2id password hashing — round-trip + tamper detection."""

from __future__ import annotations

from axis.auth.passwords import hash_password, needs_rehash, verify_password


def test_hash_round_trips() -> None:
    h = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", h)


def test_wrong_password_rejected() -> None:
    h = hash_password("right")
    assert not verify_password("wrong", h)


def test_two_hashes_of_same_password_differ() -> None:
    # argon2 carries a per-hash salt; the output must not be deterministic.
    assert hash_password("same") != hash_password("same")


def test_hash_advertises_argon2_scheme() -> None:
    assert hash_password("x").startswith("$argon2")


def test_needs_rehash_false_for_current_params() -> None:
    assert not needs_rehash(hash_password("x"))
