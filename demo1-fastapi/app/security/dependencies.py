from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.security.jwt import get_username_from_token, is_refresh_token, validate_token

bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials
    if not validate_token(token) or is_refresh_token(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的访问令牌")

    username = get_username_from_token(token)
    user = db.query(User).filter(User.username == username, User.status == 1, User.deleted == 0).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    # 检查用户角色是否包含 ADMIN（通过 sys_user_role 关联）
    from app.models.role import Role
    from app.models.user_role import UserRole
    from sqlalchemy.orm import Session as _Session
    from app.database import SessionLocal

    # 需要新 session 查角色，或直接在 get_current_user 中已查
    # 简化：通过 user.role 字段判断
    if current_user.role != "ADMIN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有权限访问该资源")
    return current_user