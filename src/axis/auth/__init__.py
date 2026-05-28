"""Authentication & authorization primitives.

Three concerns live here:

* :mod:`axis.auth.passwords` — argon2 hashing + verification.
* :mod:`axis.auth.jwt` — short-lived access-token signing and verification.
* :mod:`axis.auth.refresh` — long-lived refresh tokens with rotation and
  family-revocation on reuse (the token-theft mitigation).

The :class:`AuthenticatedPrincipal` from :mod:`axis.auth.principal` is the
unified identity surface — every endpoint sees the same shape regardless
of whether the request was authenticated via JWT or API key.
"""

from __future__ import annotations

from axis.auth.principal import AuthenticatedPrincipal, PrincipalKind

__all__ = ["AuthenticatedPrincipal", "PrincipalKind"]
