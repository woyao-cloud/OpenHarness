from datetime import datetime

from pydantic import BaseModel, Field


class UserVO(BaseModel):
    id: int
    username: str
    nickname: str | None = None
    email: str | None = None
    phone: str | None = None
    avatar: str | None = None
    status: int | None = None
    roles: list[str] = []
    create_time: datetime | None = None
    update_time: datetime | None = None

    model_config = {"from_attributes": True}


class UserCreateDTO(BaseModel):
    username: str = Field(..., min_length=3, max_length=20, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(..., min_length=6, max_length=20)
    nickname: str | None = None
    email: str | None = Field(None, pattern=r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    phone: str | None = Field(None, pattern=r"^1[3-9]\d{9}$")
    avatar: str | None = None
    status: int = 1
    role_ids: list[int] | None = None


class UserUpdateDTO(BaseModel):
    nickname: str | None = None
    email: str | None = Field(None, pattern=r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    phone: str | None = Field(None, pattern=r"^1[3-9]\d{9}$")
    avatar: str | None = None
    status: int | None = None
    role_ids: list[int] | None = None


class PasswordDTO(BaseModel):
    old_password: str = Field(..., min_length=1, description="旧密码不能为空")
    new_password: str = Field(..., min_length=6, max_length=20, description="新密码长度必须在6-20之间")


class LoginVO(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    user_info: UserVO