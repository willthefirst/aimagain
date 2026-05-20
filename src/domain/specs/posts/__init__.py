"""URL faces of the polymorphic post entity.

The internal `Post` SQLAlchemy supertype keeps its three detail tables
and audit shape; the URL layer exposes two families:

  - ``/referrals`` — kind-locked leaf (`kind='referral'`).
  - ``/openings`` — subset-supertype listing both availability subkinds
    (`kind ∈ {clinician_opening, program_intake}`). Create / edit
    dispatch via ``?kind=X`` on the URL.

See `_base.py` for the construction contract.
"""

from .opening import OPENING_ENTITY
from .referral import REFERRAL_ENTITY

__all__ = ["REFERRAL_ENTITY", "OPENING_ENTITY"]
