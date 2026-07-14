"""Development-only route family — seed-user login, persona fixtures,
and the component gallery. Mounted iff ``ENVIRONMENT == "development"``
(see `dev_auth.py` for the security rationale); production never
registers these. Not ``EntitySpec``-shaped; :mod:`src.main` imports
these modules directly. See `../README.md` for the bespoke-routes
rationale.
"""
