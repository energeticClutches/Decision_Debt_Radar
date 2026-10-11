"""Error mapping: domain errors and database constraint/trigger errors to HTTP status codes.

Trigger and constraint violations map to 409 (state conflict) or 422 (invalid input), never 500 (brief 3.9).
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError

from app.domain.errors import (
    DomainError,
    Forbidden,
    InvalidInput,
    NotFound,
    ParamsError,
    StateConflict,
    Unauthorized,
)

STATUS = {NotFound: 404, Unauthorized: 401, Forbidden: 403, StateConflict: 409, InvalidInput: 422, ParamsError: 500}


def status_for(exc: DomainError) -> int:
    for cls, code in STATUS.items():
        if isinstance(exc, cls):
            return code
    return 400


def translate_db_error(exc: DBAPIError) -> DomainError | None:
    """Map a PostgreSQL constraint or trigger error to a domain error (None when it is not a constraint error).

    - unique violation, trigger-raised check/integrity violations, RAISE EXCEPTION  -> 409 state conflict
    - table CHECK constraints, NOT NULL, foreign keys, malformed input             -> 422 invalid input
    """
    orig = exc.orig
    diag = getattr(orig, "diag", None)
    sqlstate = getattr(orig, "sqlstate", None) or getattr(diag, "sqlstate", None)
    constraint = getattr(diag, "constraint_name", None)
    message = (getattr(diag, "message_primary", None) or str(orig).splitlines()[0]).strip()
    if sqlstate == "23505":
        return StateConflict(f"Conflicts with existing data: {message}", detail={"sqlstate": sqlstate, "constraint": constraint})
    if sqlstate == "23514":
        if constraint:
            return InvalidInput(f"Value rejected by constraint {constraint}: {message}",
                                detail={"sqlstate": sqlstate, "constraint": constraint})
        return StateConflict(message, detail={"sqlstate": sqlstate})
    if sqlstate in ("23503", "23502"):
        return InvalidInput(message, detail={"sqlstate": sqlstate, "constraint": constraint})
    if sqlstate == "23000" or sqlstate == "P0001":
        return StateConflict(message, detail={"sqlstate": sqlstate})
    if sqlstate and sqlstate.startswith("22"):
        return InvalidInput(message, detail={"sqlstate": sqlstate})
    return None


def error_body(exc: DomainError) -> dict:
    return {"error": {"code": exc.code, "message": exc.message, "detail": exc.detail}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError):
        return JSONResponse(status_code=status_for(exc), content=error_body(exc))

    @app.exception_handler(DBAPIError)
    async def _db(_: Request, exc: DBAPIError):
        mapped = translate_db_error(exc)
        if mapped is None:
            raise exc
        return JSONResponse(status_code=status_for(mapped), content=error_body(mapped))

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, __: Exception):
        # Never a stack trace or an exception message in a response: the traceback goes to the server log only.
        body = {"error": {"code": "internal_error", "message": "Something went wrong on the server. Please retry.", "detail": None}}
        return JSONResponse(status_code=500, content=body)
