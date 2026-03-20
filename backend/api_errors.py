"""Shared error helpers for AleXiona API endpoints.

Every HTTPException raised through these helpers carries a structured
``detail`` dict with a machine-readable ``code`` and a human-readable
``message``, making client-side error display straightforward.
"""
from fastapi import HTTPException


def internal_error(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=500,
        detail={"code": "internal_error", "message": str(exc)},
    )


def validation_error(message: str, code: str = "validation_error") -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"code": code, "message": message},
    )


def not_found(message: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "not_found", "message": message},
    )
