import math

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.exceptions import BusinessException
from app.models.role import Role
from app.models.user import User
from app.models.user_role import UserRole
from app.schemas.common import PageResult
from app.schemas.user import PasswordDTO, UserCreateDTO, UserUpdateDTO, UserVO
from app.services.auth import _convert_to_vo, hash_password, verify_password


def get_user_page(db: Session, current: int, size: int, keyword: str | None) -> PageResult[UserVO]:
    query = db.query(User).filter(User.deleted == 0)

    if keyword:
        query = query.filter(
            or_(
                User.username.ilike(f"%{keyword}%"),
                User.nickname.ilike(f"%{keyword}%"),
                User.email.ilike(f"%{keyword}%"),
            )
        )

    query = query.order_by(User.create_time.desc())
    total = query.count()
    pages = math.ceil(total / size) if size > 0 else 0
    users = query.offset((current - 1) * size).limit(size).all()

    return PageResult(
        total=total,
        pages=pages,
        current=current,
        size=size,
        records=[_convert_to_vo(u, db) for u in users],
    )


def get_user_by_id(db: Session, user_id: int) -> UserVO:
    user = db.query(User).filter(User.id == user_id, User.deleted == 0).first()
    if user is None:
        raise BusinessException("用户不存在")
    return _convert_to_vo(user, db)


def create_user(db: Session, dto: UserCreateDTO) -> UserVO:
    existing = db.query(User).filter(User.username == dto.username, User.deleted == 0).first()
    if existing:
        raise BusinessException("用户名已存在")

    user = User(
        username=dto.username,
        password=hash_password(dto.password),
        nickname=dto.nickname,
        email=dto.email,
        phone=dto.phone,
        avatar=dto.avatar,
        status=dto.status,
        role="USER",
    )
    db.add(user)
    db.flush()

    if dto.role_ids:
        for role_id in dto.role_ids:
            db.add(UserRole(user_id=user.id, role_id=role_id))

    db.commit()
    db.refresh(user)
    return _convert_to_vo(user, db)


def update_user(db: Session, user_id: int, dto: UserUpdateDTO) -> UserVO:
    user = db.query(User).filter(User.id == user_id, User.deleted == 0).first()
    if user is None:
        raise BusinessException("用户不存在")

    if dto.nickname is not None:
        user.nickname = dto.nickname
    if dto.email is not None:
        user.email = dto.email
    if dto.phone is not None:
        user.phone = dto.phone
    if dto.avatar is not None:
        user.avatar = dto.avatar
    if dto.status is not None:
        user.status = dto.status

    if dto.role_ids is not None:
        db.query(UserRole).filter(UserRole.user_id == user_id).delete()
        for role_id in dto.role_ids:
            db.add(UserRole(user_id=user_id, role_id=role_id))

    db.commit()
    db.refresh(user)
    return _convert_to_vo(user, db)


def delete_user(db: Session, user_id: int) -> None:
    user = db.query(User).filter(User.id == user_id, User.deleted == 0).first()
    if user is None:
        raise BusinessException("用户不存在")
    user.deleted = 1
    db.commit()


def update_user_status(db: Session, user_id: int, status: int) -> None:
    user = db.query(User).filter(User.id == user_id, User.deleted == 0).first()
    if user is None:
        raise BusinessException("用户不存在")
    user.status = status
    db.commit()


def get_current_user(db: Session, user: User) -> UserVO:
    return _convert_to_vo(user, db)


def update_current_user(db: Session, user: User, dto: UserUpdateDTO) -> UserVO:
    if dto.nickname is not None:
        user.nickname = dto.nickname
    if dto.email is not None:
        user.email = dto.email
    if dto.phone is not None:
        user.phone = dto.phone
    if dto.avatar is not None:
        user.avatar = dto.avatar
    db.commit()
    db.refresh(user)
    return _convert_to_vo(user, db)


def update_password(db: Session, user: User, dto: PasswordDTO) -> None:
    if not verify_password(dto.old_password, user.password):
        raise BusinessException("旧密码错误")
    user.password = hash_password(dto.new_password)
    db.commit()