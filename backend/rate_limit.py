"""Shared slowapi Limiter instance — avoids circular imports."""
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _rate_limit_key(request: Request) -> str:
    """Rate-limit key: user_id from validated token, falling back to remote IP.

    Using user_id ensures limits are per-authenticated-user rather than
    shared across all users behind the same NAT/proxy IP.
    """
    user = getattr(request.state, "user", None)
    if user and getattr(user, "user_id", None):
        return f"user:{user.user_id}"
    return get_remote_address(request)


limiter = Limiter(key_func=_rate_limit_key, default_limits=["100/minute"])
