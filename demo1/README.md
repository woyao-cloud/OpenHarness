# User Admin System - 用户管理后台系统

基于 Spring Boot 3.x 开发的用户管理后台系统，提供完整的用户认证和管理功能。

## 🚀 技术栈

- **Spring Boot 3.2.x** - 核心框架
- **Spring Security** - 安全认证
- **JWT** - Token认证
- **MyBatis-Plus** - ORM框架
- **MySQL** - 数据库
- **Swagger/OpenAPI** - API文档

## 📋 功能特性

- ✅ 用户注册/登录/登出
- ✅ JWT Token认证与刷新
- ✅ 用户CRUD操作
- ✅ 分页查询
- ✅ 角色权限控制（ADMIN/USER）
- ✅ 统一响应格式
- ✅ 全局异常处理
- ✅ 参数校验
- ✅ API文档自动生成

## 🛠 快速开始

### 1. 数据库配置

```bash
# 创建数据库
mysql -u root -p < src/main/resources/db/schema.sql
```

### 2. 修改配置

编辑 `src/main/resources/application.yml`：

```yaml
spring:
  datasource:
    url: jdbc:mysql://localhost:3306/user_admin
    username: your_username
    password: your_password
```

### 3. 运行项目

```bash
# Maven运行
mvn spring-boot:run

# 或打包后运行
mvn clean package
java -jar target/user-admin-1.0.0.jar
```

### 4. 访问API文档

启动后访问：http://localhost:8080/swagger-ui.html

## 📡 API 接口

### 认证模块

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/auth/register` | POST | 用户注册 |
| `/api/auth/login` | POST | 用户登录 |
| `/api/auth/logout` | POST | 用户登出 |
| `/api/auth/refresh` | POST | 刷新Token |

### 用户模块

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

## 🔑 默认账号

- **用户名**: `admin`
- **密码**: `admin123`

## 📁 项目结构

```
demo1/
├── src/main/java/com/example/useradmin/
│   ├── UserAdminApplication.java      # 启动类
│   ├── config/                        # 配置类
│   ├── controller/                    # 控制器层
│   ├── service/                       # 服务层
│   ├── mapper/                        # 数据访问层
│   ├── entity/                        # 实体类
│   ├── dto/                           # 数据传输对象
│   ├── vo/                            # 视图对象
│   ├── common/                        # 通用工具
│   └── security/                      # 安全相关
├── src/main/resources/
│   ├── application.yml                # 配置文件
│   └── db/schema.sql                  # 数据库脚本
└── pom.xml                            # Maven配置
```

## 📝 请求示例

### 登录

```bash
curl -X POST http://localhost:8080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "admin123"
  }'
```

响应：
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "accessToken": "eyJhbGciOiJIUzI1NiJ9...",
    "refreshToken": "eyJhbGciOiJIUzI1NiJ9...",
    "expiresIn": 86400,
    "userInfo": {
      "id": 1,
      "username": "admin",
      "nickname": "管理员",
      "role": "ADMIN"
    }
  }
}
```

### 使用Token访问受保护接口

```bash
curl -X GET http://localhost:8080/api/users/profile \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9..."
```

## 🔒 安全说明

- 所有密码使用 BCrypt 加密存储
- JWT Token 有效期：24小时
- Refresh Token 有效期：7天
- 支持接口级别的权限控制


  生成的文件

   1. demo1/docker-compose.yml
     • MySQL 服务：使用 MySQL 8.0，自动挂载 schema.sql 初始化数据库
     • Spring Boot 应用：从 Dockerfile 构建，连接 MySQL 服务
     • 健康检查：确保 MySQL 就绪后才启动应用

   2. demo1/Dockerfile
     • 多阶段构建，使用 Maven 编译 + JRE 运行
     • 基于 Alpine Linux，镜像体积小

   3. demo1/src/main/resources/application-docker.yml
     • Docker 环境的配置文件，支持环境变量注入

   使用方法

     ╭─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
     │ bash                                                                                                                                                                                                                    │
     │ cd demo1                                                                                                                                                                                                                │
     │ # 构建并启动服务                                                                                                                                                                                                        │
     │ docker-compose up --build                                                                                                                                                                                               │
     │ # 后台运行                                                                                                                                                                                                              │
     │ docker-compose up -d --build                                                                                                                                                                                            │
     │ # 查看日志                                                                                                                                                                                                              │
     │ docker-compose logs -f                                                                                                                                                                                                  │
     │ # 停止服务                                                                                                                                                                                                              │
     │ docker-compose down                                                                                                                                                                                                     │
     │ # 停止并删除数据卷                                                                                                                                                                                                      │
     │ docker-compose down -v                                                                                                                                                                                                  │
     ╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

   初始化数据
   首次启动时，MySQL 会自动执行 db/schema.sql：
     • 创建 user_admin 数据库
     • 创建 sys_user 用户表
     • 插入默认管理员账号：admin / admin123
