import math

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.exceptions import BusinessException
from app.models.role import Role
from app.schemas.common import PageResult
from app.schemas.role import RoleCreateDTO, RoleQueryDTO, RoleUpdateDTO, RoleVO


def _convert_to_vo(role: Role) -> RoleVO:
    return RoleVO(
        id=role.id,
        role_code=role.role_code,
        role_name=role.role_name,
        description=role.description,
        status=role.status,
        create_time=role.create_time,
        update_time=role.update_time,
    )


def get_role_page(db: Session, query_dto: RoleQueryDTO) -> PageResult[RoleVO]:
    query = db.query(Role).filter(Role.deleted == 0)

    if query_dto.keyword:
        query = query.filter(
            or_(
                Role.role_code.ilike(f"%{query_dto.keyword}%"),
                Role.role_name.ilike(f"%{query_dto.keyword}%"),
            )
        )

    if query_dto.status is not None:
        query = query.filter(Role.status == query_dto.status)

    query = query.order_by(Role.role_code.asc())
    total = query.count()
    pages = math.ceil(total / query_dto.size) if query_dto.size > 0 else 0
    roles = query.offset((query_dto.current - 1) * query_dto.size).limit(query_dto.size).all()

    return PageResult(
        total=total,
        pages=pages,
        current=query_dto.current,
        size=query_dto.size,
        records=[_convert_to_vo(r) for r in roles],
    )


def get_role_by_id(db: Session, role_id: int) -> RoleVO:
    role = db.query(Role).filter(Role.id == role_id, Role.deleted == 0).first()
    if role is None:
        raise BusinessException("角色不存在")
    return _convert_to_vo(role)


def create_role(db: Session, dto: RoleCreateDTO) -> RoleVO:
    existing = db.query(Role).filter(Role.role_code == dto.role_code, Role.deleted == 0).first()
    if existing:
        raise BusinessException("角色编码已存在")

    role = Role(
        role_code=dto.role_code,
        role_name=dto.role_name,
        description=dto.description,
        status=dto.status,
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return _convert_to_vo(role)


def update_role(db: Session, role_id: int, dto: RoleUpdateDTO) -> RoleVO:
    role = db.query(Role).filter(Role.id == role_id, Role.deleted == 0).first()
    if role is None:
        raise BusinessException("角色不存在")

    role.role_name = dto.role_name
    if dto.description is not None:
        role.description = dto.description
    if dto.status is not None:
        role.status = dto.status

    db.commit()
    db.refresh(role)
    return _convert_to_vo(role)


def delete_role(db: Session, role_id: int) -> None:
    role = db.query(Role).filter(Role.id == role_id, Role.deleted == 0).first()
    if role is None:
        raise BusinessException("角色不存在")
    role.deleted = 1
    db.commit()


def update_role_status(db: Session, role_id: int, status: int) -> None:
    role = db.query(Role).filter(Role.id == role_id, Role.deleted == 0).first()
    if role is None:
        raise BusinessException("角色不存在")
    role.status = status
    db.commit()


def get_all_active_roles(db: Session) -> list[RoleVO]:
    roles = db.query(Role).filter(Role.status == 1, Role.deleted == 0).order_by(Role.role_code).all()
    return [_convert_to_vo(r) for r in roles]