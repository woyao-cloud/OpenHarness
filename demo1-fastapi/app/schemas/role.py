from datetime import datetime

from pydantic import BaseModel, Field


class RoleVO(BaseModel):
    id: int
    role_code: str
    role_name: str
    description: str | None = None
    status: int | None = None
    create_time: datetime | None = None
    update_time: datetime | None = None

    model_config = {"from_attributes": True}


class RoleCreateDTO(BaseModel):
    role_code: str = Field(..., max_length=50, description="角色编码不能为空")
    role_name: str = Field(..., max_length=50, description="角色名称不能为空")
    description: str | None = Field(None, max_length=200)
    status: int = 1


class RoleUpdateDTO(BaseModel):
    role_name: str = Field(..., max_length=50, description="角色名称不能为空")
    description: str | None = Field(None, max_length=200)
    status: int | None = None


class RoleQueryDTO(BaseModel):
    keyword: str | None = None
    status: int | None = None
    current: int = 1
    size: int = 10