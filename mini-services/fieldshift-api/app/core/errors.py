"""Structured error envelope + exception hierarchy.

Every client-facing error follows the Master Engineering Prompt §42.5:

    {"error": {"code": ..., "message": ..., "details": [...], "request_id": ...}}
"""

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger("fieldshift.errors")


class FieldShiftError(Exception):
    """Base class for domain errors that map to structured API errors."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "BAD_REQUEST"

    def __init__(
        self,
        message: str,
        *,
        details: list[dict[str, Any]] | None = None,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or []
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code


class ValidationFailed(FieldShiftError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "VALIDATION_FAILED"


class InvalidGeometry(FieldShiftError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "INVALID_GEOMETRY"


class UnsupportedVariable(FieldShiftError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "UNSUPPORTED_VARIABLE"


class InvalidDateRange(FieldShiftError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "INVALID_DATE_RANGE"


class NotFound(FieldShiftError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"


class Unauthorized(FieldShiftError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHORIZED"


class Forbidden(FieldShiftError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"


class Conflict(FieldShiftError):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"


class InsufficientData(FieldShiftError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "INSUFFICIENT_DATA"


class ProviderRequestError(FieldShiftError):
    """A provider rejected the request (bad params, out-of-coverage, API error body)."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "PROVIDER_REQUEST_ERROR"


class ProviderUnavailable(FieldShiftError):
    """An optional provider is unreachable/degraded. Other providers are unaffected."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "PROVIDER_UNAVAILABLE"


def _error_payload(
    code: str,
    message: str,
    details: list[dict[str, Any]] | None,
    request_id: str,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or [],
            "request_id": request_id,
        }
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(FieldShiftError)
    async def domain_error_handler(request: Request, exc: FieldShiftError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(exc.code, exc.message, exc.details, request_id),
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        details = [
            {
                "field": ".".join(str(loc) for loc in err.get("loc", [])),
                "reason": err.get("msg", "invalid value"),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_error_payload("VALIDATION_FAILED", "Request payload failed validation.", details, request_id),
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        # Never leak SQL or driver details to clients (Master Prompt §42.5).
        logger.exception("database error", extra={"request_id": request_id})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_payload(
                "INTERNAL_ERROR", "An internal database error occurred.", None, request_id
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        logger.exception("unhandled error", extra={"request_id": request_id})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_payload(
                "INTERNAL_ERROR", "An unexpected internal error occurred.", None, request_id
            ),
        )
