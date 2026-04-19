# User Admin System - 用户管理后台系统 (FastAPI 版本)

基于 FastAPI 开发的用户管理后台系统，功能与 Spring Boot 版本完全对等。

## 🚀 技术栈

- **FastAPI** - Web 框架
- **SQLAlchemy 2.0** - ORM
- **PyJWT** - Token 认证
- **passlib/bcrypt** - 密码加密
- **Pydantic v2** - 数据验证
- **PostgreSQL** - 数据库
- **Uvicorn** - ASGI 服务器

## 📋 功能特性

- ✅ 用户注册/登录/登出
- ✅ JWT Token 认证与刷新
- ✅ 用户 CRUD 操作
- ✅ 分页查询
- ✅ 角色权限控制（ADMIN/USER）
- ✅ 统一响应格式
- ✅ 全局异常处理
- ✅ 参数校验（Pydantic）
- ✅ API 文档自动生成（Swagger UI）

## 🛠 快速开始

### 方式一：Docker Compose（推荐）

```bash
# 构建并启动
docker-compose up -d --build

# 查看日志
docker-compose logs -f

# 停止
docker-compose down
```

### 方式二：本地运行

```bash
# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate    # Windows

# 安装依赖
pip install -r requirements.txt

# 启动
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 访问 API 文档

启动后访问：http://localhost:8000/docs

## 📡 API 接口

### 认证模块 `/api/auth`

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/auth/register` | POST | 用户注册 |
| `/api/auth/login` | POST | 用户登录 |
| `/api/auth/logout` | POST | 用户登出 |
| `/api/auth/refresh` | POST | 刷新 Token |

### 用户模块 `/api/users`

| 接口 | 方法 | 说明 | 权限 |
|------|------|------|------|
| `/api/users` | GET | 分页查询用户 | ADMIN |
| `/api/users/{id}` | GET | 查询用户详情 | ADMIN |
| `/api/users` | POST | 创建用户 | ADMIN |
| `/api/users/{id}` | PUT | 更新用户 | ADMIN |
| `/api/users/{id}` | DELETE | 删除用户 | ADMIN |
| `/api/users/{id}/status` | PUT | 修改用户状态 | ADMIN |
| `/api/users/profile` | GET | 获取当前用户信息 | 登录用户 |
| `/api/users/profile` | PUT | 更新当前用户信息 | 登录用户 |
| `/api/users/password` | PUT | 修改密码 | 登录用户 |

### 角色模块 `/api/roles`

| 接口 | 方法 | 说明 | 权限 |
|------|------|------|------|
| `/api/roles` | GET | 分页查询角色 | ADMIN |
| `/api/roles/all` | GET | 获取全部有效角色 | ADMIN |
| `/api/roles/{id}` | GET | 角色详情 | ADMIN |
| `/api/roles` | POST | 创建角色 | ADMIN |
| `/api/roles/{id}` | PUT | 更新角色 | ADMIN |
| `/api/roles/{id}` | DELETE | 删除角色 | ADMIN |
| `/api/roles/{id}/status` | PUT | 修改角色状态 | ADMIN |

## 🔑 默认账号

- **用户名**: `admin`
- **密码**: `admin123`

## 📁 项目结构

```
demo1-fastapi/
├── app/
│   ├── main.py              # 应用入口
│   ├── config.py            # 配置
│   ├── database.py          # 数据库连接
│   ├── exceptions.py        # 异常定义
│   ├── models/              # SQLAlchemy 模型
│   ├── schemas/             # Pydantic 模型 (DTO/VO)
│   ├── routers/             # 路由 (Controller)
│   ├── services/            # 业务逻辑 (Service)
│   └── security/            # JWT 认证
├── db/
│   └── schema-postgres.sql  # 数据库脚本
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env
└── README.md
```

## 📝 请求示例

### 登录

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin123"}'
```

### 使用 Token 访问

```bash
curl http://localhost:8000/api/users/profile \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9..."
```

## 🔒 安全说明

- 所有密码使用 BCrypt 加密存储
- JWT Token 有效期：24 小时
- Refresh Token 有效期：7 天
- ADMIN 角色才能访问管理接口