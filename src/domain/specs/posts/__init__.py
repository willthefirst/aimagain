"""Per-kind faces of the polymorphic post entity.

The internal `Post` SQLAlchemy supertype keeps its three detail tables
and audit shape; the URL layer exposes each kind as its own resource
family — ``/referrals``, ``/openings``, ``/intakes``. See `_base.py`
for the construction contract.
"""

from .intake import INTAKE_ENTITY
from .opening import OPENING_ENTITY
from .referral import REFERRAL_ENTITY

__all__ = ["REFERRAL_ENTITY", "OPENING_ENTITY", "INTAKE_ENTITY"]
