from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.common import PageResult, Result
from app.schemas.user import PasswordDTO, UserCreateDTO, UserUpdateDTO, UserVO
from app.security.dependencies import get_current_user, require_admin
from app.services import user as user_service

router = APIRouter(prefix="/api/users", tags=["用户管理"])


@router.get("", summary="分页查询用户列表（管理员）")
def get_user_page(
    current: int = Query(1, description="当前页"),
    size: int = Query(10, description="每页大小"),
    keyword: str | None = Query(None, description="搜索关键词"),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Result[PageResult[UserVO]]:
    return Result.success(user_service.get_user_page(db, current, size, keyword))


@router.get("/{user_id}", summary="获取用户详情（管理员）")
def get_user_by_id(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Result[UserVO]:
    return Result.success(user_service.get_user_by_id(db, user_id))


@router.post("", summary="创建用户（管理员）")
def create_user(
    dto: UserCreateDTO,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Result[UserVO]:
    return Result.success(user_service.create_user(db, dto))


@router.put("/{user_id}", summary="更新用户（管理员）")
def update_user(
    user_id: int,
    dto: UserUpdateDTO,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Result[UserVO]:
    return Result.success(user_service.update_user(db, user_id, dto))


@router.delete("/{user_id}", summary="删除用户（管理员）")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Result[None]:
    user_service.delete_user(db, user_id)
    return Result.success()


@router.put("/{user_id}/status", summary="修改用户状态（管理员）")
def update_user_status(
    user_id: int,
    body: dict,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Result[None]:
    user_service.update_user_status(db, user_id, body.get("status", 1))
    return Result.success()


@router.get("/profile", summary="获取当前登录用户信息")
def get_current_user_info(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Result[UserVO]:
    return Result.success(user_service.get_current_user(db, current_user))


@router.put("/profile", summary="更新当前登录用户信息")
def update_current_user(
    dto: UserUpdateDTO,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Result[UserVO]:
    return Result.success(user_service.update_current_user(db, current_user, dto))


@router.put("/password", summary="修改当前登录用户密码")
def update_password(
    dto: PasswordDTO,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Result[None]:
    user_service.update_password(db, current_user, dto)
    return Result.success()