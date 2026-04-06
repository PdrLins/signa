"""FastAPI dependency injection functions."""

from fastapi import HTTPException, Request, status


async def get_current_user(request: Request) -> dict:
    """Get the current authenticated user from request state.

    The auth middleware already validated the JWT and populated
    request.state.user. This dependency just reads it.

    Raises:
        HTTPException 401 if no user is set (middleware rejected the request).
    """
    user = getattr(request.state, "user", None)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user
