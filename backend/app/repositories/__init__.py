"""Data access. Repositories receive a Session, run queries and never commit (only services open transactions).

Numeric database values (Decimal) are converted to float when building domain objects (EvidenceFacts) and
API payloads. Domain code never sees Decimal or ORM objects.
"""
