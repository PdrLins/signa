"""Custom exception handlers for the FastAPI app."""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from loguru import logger

from app.core.utils import get_client_ip


class AuthenticationError(Exception):
    def __init__(self, detail: str = "Authentication failed"):
        self.detail = detail


class RateLimitExceeded(Exception):
    def __init__(self, detail: str = "Rate limit exceeded", retry_after: int = 900):
        self.detail = detail
        self.retry_after = retry_after


class OTPExpiredError(Exception):
    def __init__(self, detail: str = "OTP has expired"):
        self.detail = detail


class OTPInvalidError(Exception):
    def __init__(self, detail: str = "Invalid OTP code", attempts_remaining: int = 0):
        self.detail = detail
        self.attempts_remaining = attempts_remaining


def register_exception_handlers(app: FastAPI) -> None:
    """Register all custom exception handlers on the FastAPI app."""

    @app.exception_handler(AuthenticationError)
    async def auth_error_handler(request: Request, exc: AuthenticationError):
        logger.warning(f"Auth error from {get_client_ip(request)}")
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": exc.detail},
        )

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        logger.warning(f"Rate limit from {get_client_ip(request)}")
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": exc.detail},
            headers={"Retry-After": str(exc.retry_after)},
        )

    @app.exception_handler(OTPExpiredError)
    async def otp_expired_handler(request: Request, exc: OTPExpiredError):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": exc.detail},
        )

    @app.exception_handler(OTPInvalidError)
    async def otp_invalid_handler(request: Request, exc: OTPInvalidError):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "detail": exc.detail,
                "attempts_remaining": exc.attempts_remaining,
            },
        )
