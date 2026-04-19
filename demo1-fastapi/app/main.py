from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.exceptions import BusinessException
from app.routers import auth, roles, users
from app.schemas.common import Result

app = FastAPI(title="用户管理后台", description="基于 FastAPI 的用户管理系统", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局异常处理
@app.exception_handler(BusinessException)
async def business_exception_handler(request: Request, exc: BusinessException):
    return JSONResponse(status_code=200, content=Result.error(exc.message, exc.code).model_dump())


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content=Result.error("系统繁忙，请稍后重试").model_dump())


# 注册路由
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(roles.router)


@app.get("/", summary="健康检查")
def root():
    return Result.success("用户管理后台系统运行中")