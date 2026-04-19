from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.common import PageResult, Result
from app.schemas.role import RoleCreateDTO, RoleQueryDTO, RoleUpdateDTO, RoleVO
from app.security.dependencies import require_admin
from app.services import role as role_service

router = APIRouter(prefix="/api/roles", tags=["角色管理"])


@router.get("", summary="分页查询角色列表")
def get_role_page(
    query_dto: RoleQueryDTO = Depends(),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Result[PageResult[RoleVO]]:
    return Result.success(role_service.get_role_page(db, query_dto))


@router.get("/all", summary="获取所有有效角色列表（用于下拉选择）")
def get_all_active_roles(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Result[list[RoleVO]]:
    return Result.success(role_service.get_all_active_roles(db))


@router.get("/{role_id}", summary="获取角色详情")
def get_role_by_id(
    role_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Result[RoleVO]:
    return Result.success(role_service.get_role_by_id(db, role_id))


@router.post("", summary="创建角色")
def create_role(
    dto: RoleCreateDTO,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Result[RoleVO]:
    return Result.success(role_service.create_role(db, dto))


@router.put("/{role_id}", summary="更新角色")
def update_role(
    role_id: int,
    dto: RoleUpdateDTO,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Result[RoleVO]:
    return Result.success(role_service.update_role(db, role_id, dto))


@router.delete("/{role_id}", summary="删除角色")
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Result[None]:
    role_service.delete_role(db, role_id)
    return Result.success()


@router.put("/{role_id}/status", summary="修改角色状态")
def update_role_status(
    role_id: int,
    body: dict,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Result[None]:
    role_service.update_role_status(db, role_id, body.get("status", 1))
    return Result.success()