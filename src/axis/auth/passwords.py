"""Password hashing — argon2id via passlib.

argon2id is the OWASP-recommended default for new applications: it is
memory-hard, has a tunable cost, and resists the GPU-acceleration attacks
that have eroded bcrypt's safety margin.

:func:`needs_rehash` enables transparent cost upgrades over time without
breaking existing logins: after a successful :func:`verify_password`, the
caller can re-hash and persist if this returns ``True``.
"""

from __future__ import annotations

from passlib.context import CryptContext

_pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto",
    argon2__rounds=3,  # passlib default; safe for an API in 2026
    argon2__memory_cost=65_536,  # 64 MiB — within the OWASP guidance band
    argon2__parallelism=4,
)


def hash_password(plaintext: str) -> str:
    """Return the argon2id hash for ``plaintext``."""
    return _pwd_context.hash(plaintext)


def verify_password(plaintext: str, hashed: str) -> bool:
    """Return ``True`` iff ``plaintext`` is the correct password for ``hashed``."""
    return _pwd_context.verify(plaintext, hashed)


def needs_rehash(hashed: str) -> bool:
    """Return ``True`` if ``hashed`` should be re-hashed with current parameters."""
    return _pwd_context.needs_update(hashed)
