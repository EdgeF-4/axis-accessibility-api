"""ORM mappers.

Importing this package registers every mapper with ``Base.metadata`` so that
Alembic, ``create_all``, and the seed loader see the full schema.
"""

from __future__ import annotations

from axis.db.models.datapoint import Datapoint
from axis.db.models.enums import (
    JobStatus,
    Provenance,
    ReviewStatus,
    ValueType,
)
from axis.db.models.iam import (
    ApiKey,
    RefreshToken,
    Role,
    RoleAssignment,
    RoleScope,
    Scope,
    User,
)
from axis.db.models.ingestion import DLQEntry, IngestionJob, ReviewItem
from axis.db.models.taxonomy import (
    AttributeEnumValue,
    TaxonomyAttribute,
    TaxonomyCategory,
    TaxonomyVersion,
)
from axis.db.models.venue import Venue

__all__ = [
    "ApiKey",
    "AttributeEnumValue",
    "DLQEntry",
    "Datapoint",
    "IngestionJob",
    "JobStatus",
    "Provenance",
    "RefreshToken",
    "ReviewItem",
    "ReviewStatus",
    "Role",
    "RoleAssignment",
    "RoleScope",
    "Scope",
    "TaxonomyAttribute",
    "TaxonomyCategory",
    "TaxonomyVersion",
    "User",
    "ValueType",
    "Venue",
]
