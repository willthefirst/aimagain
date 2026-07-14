"""The clinician-credential spec trio, grouped because they share one shape.

Certification / education / licensure have identical `EntitySpec`
structure — owned subentities of Clinician declared through
:func:`._credential.make_clinician_credential_entity`, the single home
of the shared shape. Each module differs only in identity, audit
actions, and schemas; see `_credential.py` for the full rationale.
"""

from .clinician_certification import CERTIFICATION_ENTITY
from .clinician_education import EDUCATION_ENTITY
from .clinician_licensure import LICENSURE_ENTITY

__all__ = [
    "CERTIFICATION_ENTITY",
    "EDUCATION_ENTITY",
    "LICENSURE_ENTITY",
]
