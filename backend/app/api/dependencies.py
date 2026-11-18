from fastapi import Depends, HTTPException

from app.api.routes.auth import get_current_user
from app.models.user import User


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Administrator access is required.")
    return user
