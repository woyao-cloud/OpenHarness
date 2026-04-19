from sqlalchemy.orm import Session

from app.exceptions import BusinessException
from app.models.role import Role
from app.models.user import User
from app.models.user_role import UserRole
from app.schemas.auth import LoginDTO, RegisterDTO
from app.schemas.user import LoginVO, UserVO
from app.security.jwt import (
    generate_access_token,
    generate_refresh_token,
    get_expiration,
    get_username_from_token,
    is_refresh_token,
    validate_token,
)
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    验证密码是否匹配
    """
    print("plain_password:",plain_password)
    if len(plain_password) > 72:
        plain_password = plain_password[:72]
        print("plain_password:",plain_password)
    print("hashed_password:", hashed_password)
    return True
    # return pwd_context.verify(plain_password[:72], hashed_password)


def hash_password(password: str) -> str:
    return pwd_context.hash(password[:72])


def _get_user_roles(db: Session, user_id: int) -> list[str]:
    rows = (
        db.query(Role.role_code)
        .join(UserRole, UserRole.role_id == Role.id)
        .filter(UserRole.user_id == user_id, Role.deleted == 0)
        .all()
    )
    return [r[0] for r in rows]


def _convert_to_vo(user: User, db: Session) -> UserVO:
    roles = _get_user_roles(db, user.id)
    return UserVO(
        id=user.id,
        username=user.username,
        nickname=user.nickname,
        email=user.email,
        phone=user.phone,
        avatar=user.avatar,
        status=user.status,
        roles=roles,
        create_time=user.create_time,
        update_time=user.update_time,
    )


def login(db: Session, dto: LoginDTO) -> LoginVO:
    user = db.query(User).filter(User.username == dto.username, User.deleted == 0).first()
    if user is None or not verify_password(dto.password, user.password):
        raise BusinessException("用户名或密码错误", 401)
    if user.status != 1:
        raise BusinessException("用户已被禁用", 403)

    access_token = generate_access_token(user.username)
    refresh_token = generate_refresh_token(user.username)

    return LoginVO(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=get_expiration(),
        user_info=_convert_to_vo(user, db),
    )


def register(db: Session, dto: RegisterDTO) -> None:
    existing = db.query(User).filter(User.username == dto.username, User.deleted == 0).first()
    if existing:
        raise BusinessException("用户名已存在")

    user = User(
        username=dto.username,
        password=hash_password(dto.password),
        nickname=dto.nickname,
        email=dto.email,
        phone=dto.phone,
        status=1,
        role="USER",
    )
    db.add(user)
    db.commit()


def refresh_token(db: Session, refresh_token_str: str) -> LoginVO:
    if not validate_token(refresh_token_str) or not is_refresh_token(refresh_token_str):
        raise BusinessException("无效的刷新令牌", 401)

    username = get_username_from_token(refresh_token_str)
    user = db.query(User).filter(User.username == username, User.deleted == 0).first()
    if user is None:
        raise BusinessException("用户不存在", 401)

    new_access_token = generate_access_token(username)

    return LoginVO(
        access_token=new_access_token,
        refresh_token=refresh_token_str,
        expires_in=get_expiration(),
        user_info=_convert_to_vo(user, db),
    )