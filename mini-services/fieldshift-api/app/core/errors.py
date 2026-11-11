"""Structured error envelope + exception hierarchy.

Every client-facing error follows the Master Engineering Prompt §42.5:

    {"error": {"code": ..., "message": ..., "details": [...], "request_id": ...}}
"""

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger("croptwist.errors")


class CropTwistError(Exception):
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


class ValidationFailed(CropTwistError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "VALIDATION_FAILED"


class InvalidGeometry(CropTwistError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "INVALID_GEOMETRY"


class UnsupportedVariable(CropTwistError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "UNSUPPORTED_VARIABLE"


class InvalidDateRange(CropTwistError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "INVALID_DATE_RANGE"


class NotFound(CropTwistError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"


class Unauthorized(CropTwistError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHORIZED"


class Forbidden(CropTwistError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"


class Conflict(CropTwistError):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"


class PaymentRequired(CropTwistError):
    """Entitlement/subscription gate (P3 W2): plan limit reached or no
    active subscription. Maps to HTTP 402 Payment Required so clients can
    drive the upgrade flow from a single, machine-readable signal."""

    status_code = 402  # HTTP 402 Payment Required
    code = "PAYMENT_REQUIRED"


class AccountLocked(CropTwistError):
    """Sign-in blocked by the temporary failed-login lockout (P0-2).

    Carries `retry_after_seconds` so clients can show a countdown; the value
    is also rendered into the structured error details.
    """

    status_code = 423  # HTTP 423 Locked
    code = "ACCOUNT_LOCKED"

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: int,
        details: list[dict[str, Any]] | None = None,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(
            message,
            details=[{"retry_after_seconds": retry_after_seconds}] + (details or []),
            code=code,
            status_code=status_code,
        )
        self.retry_after_seconds = retry_after_seconds


class TooManyRequests(CropTwistError):
    """Sliding-window rate limit exceeded (P0-2). Carries `retry_after_seconds`."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "RATE_LIMITED"

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: int,
        details: list[dict[str, Any]] | None = None,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(
            message,
            details=[{"retry_after_seconds": retry_after_seconds}] + (details or []),
            code=code,
            status_code=status_code,
        )
        self.retry_after_seconds = retry_after_seconds


class EmailNotVerified(CropTwistError):
    """Sign-in denied because the account's email address is not verified (P0-2)."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "EMAIL_NOT_VERIFIED"


class InsufficientData(CropTwistError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "INSUFFICIENT_DATA"


class ProviderRequestError(CropTwistError):
    """A provider rejected the request (bad params, out-of-coverage, API error body)."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "PROVIDER_REQUEST_ERROR"


class ProviderUnavailable(CropTwistError):
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
    @app.exception_handler(CropTwistError)
    async def domain_error_handler(request: Request, exc: CropTwistError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        headers = None
        if isinstance(exc, (TooManyRequests, AccountLocked)):
            # Rate limiter and lockout advertise when the client may retry.
            headers = {"Retry-After": str(max(int(exc.retry_after_seconds), 1))}
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(exc.code, exc.message, exc.details, request_id),
            headers=headers,
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
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_error_payload("VALIDATION_FAILED", "Request payload failed validation.", details, request_id),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        # Deepening F-16: framework-raised HTTP errors (unmatched path 404,
        # wrong method 405, malformed multipart, ...) previously bypassed the
        # structured envelope. They now use the same shape with a request id.
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(
            exc.status_code, "HTTP_ERROR"
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(code, str(exc.detail), None, request_id),
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
