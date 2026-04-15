# 前端角色管理功能调整计划

## 已完成 ✅
- [x] 更新 types/index.ts - 添加 RoleVO 和相关 DTO 类型，修改 UserVO 支持多角色
- [x] 创建 api/role.ts - 角色管理 API
- [x] 更新 api/index.ts - 导出 roleApi
- [x] 更新 router/index.tsx - 添加角色管理路由，更新权限判断逻辑
- [x] 更新 components/layout/MainLayout.tsx - 添加角色管理菜单
- [x] 创建 pages/RoleList.tsx - 角色列表页面
- [x] 创建 pages/RoleDetail.tsx - 角色编辑/新增页面
- [x] 更新 pages/UserList.tsx - 显示多角色标签
- [x] 更新 pages/UserDetail.tsx - 支持多角色选择
- [x] 后端更新 - UserMapper 添加查询角色方法
- [x] 后端更新 - UserServiceImpl 支持角色查询和保存
- [x] 后端更新 - UserCreateDTO/UserUpdateDTO 添加 roleIds 字段
- [x] 后端更新 - UserDetailsServiceImpl 从 sys_user_role 获取角色

## 全部完成 ✅
