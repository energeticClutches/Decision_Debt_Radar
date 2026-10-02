"""Pure business logic (no SQLAlchemy, FastAPI or psycopg imports).

- facts.py: EvidenceFacts, the one immutable input structure of the DDI and NBE engines (R4)
- ddi/: Decision Debt Index engine (docs/DDI-spec.md)
- nbe/: Next Best Evidence engine (docs/NBE-spec.md)
- lifecycle.py, permissions.py: lifecycle transition table and role permission matrix
"""
