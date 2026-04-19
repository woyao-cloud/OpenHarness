from pydantic import BaseModel, Field


class LoginDTO(BaseModel):
    username: str = Field(..., min_length=1, description="用户名不能为空")
    password: str = Field(..., min_length=1, description="密码不能为空")


class RegisterDTO(BaseModel):
    username: str = Field(..., min_length=3, max_length=20, pattern=r"^[a-zA-Z0-9_]+$", description="用户名只能包含字母、数字和下划线")
    password: str = Field(..., min_length=6, max_length=20)
    nickname: str | None = None
    email: str | None = Field(None, pattern=r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    phone: str | None = Field(None, pattern=r"^1[3-9]\d{9}$")


class RefreshTokenDTO(BaseModel):
    refreshToken: str