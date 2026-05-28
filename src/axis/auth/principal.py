"""The unified authenticated-principal abstraction.

Endpoints never branch on "JWT user vs. API key" — they receive an
:class:`AuthenticatedPrincipal` and check the requested scope. Whether the
request was authenticated via OAuth2 bearer or partner ``X-API-Key`` is
folded behind this type.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID


class PrincipalKind(enum.StrEnum):
    """The flavour of credential a principal was authenticated with."""

    USER = "user"
    API_KEY = "api_key"


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """A resolved identity carrying its effective scopes.

    Attributes:
      kind: which credential type was presented.
      subject_id: ``user.id`` if kind is USER; ``api_key.id`` if API_KEY.
      display: human-readable identifier shown in logs (email, partner org).
      scopes: effective scope set the principal is allowed to assert.
    """

    kind: PrincipalKind
    subject_id: UUID
    display: str
    scopes: frozenset[str] = field(default_factory=frozenset)

    def has_scope(self, scope: str) -> bool:
        """Return ``True`` iff ``scope`` is in this principal's effective set."""
        return scope in self.scopes
