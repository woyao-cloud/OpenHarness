from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.auth import LoginDTO, RefreshTokenDTO, RegisterDTO
from app.schemas.common import Result
from app.schemas.user import LoginVO
from app.services import auth as auth_service

router = APIRouter(prefix="/api/auth", tags=["认证管理"])


@router.post("/login", summary="用户登录")
def login(dto: LoginDTO, db: Session = Depends(get_db)) -> Result[LoginVO]:
    return Result.success(auth_service.login(db, dto))


@router.post("/register", summary="用户注册")
def register(dto: RegisterDTO, db: Session = Depends(get_db)) -> Result[None]:
    auth_service.register(db, dto)
    return Result.success()


@router.post("/refresh", summary="刷新Token")
def refresh_token(dto: RefreshTokenDTO, db: Session = Depends(get_db)) -> Result[LoginVO]:
    return Result.success(auth_service.refresh_token(db, dto.refreshToken))


@router.post("/logout", summary="用户登出")
def logout() -> Result[None]:
    return Result.success()