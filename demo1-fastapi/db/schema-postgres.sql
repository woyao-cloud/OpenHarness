-- 用户管理后台数据库脚本 (PostgreSQL 版本)

-- 用户表
CREATE TABLE IF NOT EXISTS sys_user (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password VARCHAR(100) NOT NULL,
    nickname VARCHAR(50) DEFAULT NULL,
    email VARCHAR(100) DEFAULT NULL,
    phone VARCHAR(20) DEFAULT NULL,
    avatar VARCHAR(200) DEFAULT NULL,
    status SMALLINT DEFAULT 1,
    role VARCHAR(20) DEFAULT 'USER',
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted SMALLINT DEFAULT 0
);

COMMENT ON TABLE sys_user IS '用户表';
COMMENT ON COLUMN sys_user.id IS '主键ID';
COMMENT ON COLUMN sys_user.username IS '用户名';
COMMENT ON COLUMN sys_user.password IS '密码';
COMMENT ON COLUMN sys_user.nickname IS '昵称';
COMMENT ON COLUMN sys_user.email IS '邮箱';
COMMENT ON COLUMN sys_user.phone IS '手机号';
COMMENT ON COLUMN sys_user.avatar IS '头像URL';
COMMENT ON COLUMN sys_user.status IS '状态：0-禁用，1-启用';
COMMENT ON COLUMN sys_user.role IS '角色：ADMIN/USER';
COMMENT ON COLUMN sys_user.create_time IS '创建时间';
COMMENT ON COLUMN sys_user.update_time IS '更新时间';
COMMENT ON COLUMN sys_user.deleted IS '逻辑删除：0-未删除，1-已删除';

CREATE INDEX IF NOT EXISTS idx_username ON sys_user(username);
CREATE INDEX IF NOT EXISTS idx_status ON sys_user(status);

-- 角色表
CREATE TABLE IF NOT EXISTS sys_role (
    id BIGSERIAL PRIMARY KEY,
    role_code VARCHAR(50) NOT NULL UNIQUE,
    role_name VARCHAR(50) NOT NULL,
    description VARCHAR(200) DEFAULT NULL,
    status SMALLINT DEFAULT 1,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted SMALLINT DEFAULT 0
);

COMMENT ON TABLE sys_role IS '角色表';
COMMENT ON COLUMN sys_role.id IS '主键ID';
COMMENT ON COLUMN sys_role.role_code IS '角色编码';
COMMENT ON COLUMN sys_role.role_name IS '角色名称';
COMMENT ON COLUMN sys_role.description IS '角色描述';
COMMENT ON COLUMN sys_role.status IS '状态：0-禁用，1-启用';
COMMENT ON COLUMN sys_role.create_time IS '创建时间';
COMMENT ON COLUMN sys_role.update_time IS '更新时间';
COMMENT ON COLUMN sys_role.deleted IS '逻辑删除：0-未删除，1-已删除';

CREATE INDEX IF NOT EXISTS idx_role_code ON sys_role(role_code);
CREATE INDEX IF NOT EXISTS idx_role_status ON sys_role(status);

-- 用户角色关联表
CREATE TABLE IF NOT EXISTS sys_user_role (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    CONSTRAINT uk_user_role UNIQUE (user_id, role_id)
);

COMMENT ON TABLE sys_user_role IS '用户角色关联表';
COMMENT ON COLUMN sys_user_role.id IS '主键ID';
COMMENT ON COLUMN sys_user_role.user_id IS '用户ID';
COMMENT ON COLUMN sys_user_role.role_id IS '角色ID';

CREATE INDEX IF NOT EXISTS idx_ur_user_id ON sys_user_role(user_id);
CREATE INDEX IF NOT EXISTS idx_ur_role_id ON sys_user_role(role_id);

-- 自动更新时间触发器
CREATE OR REPLACE FUNCTION update_update_time_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_sys_user_update_time ON sys_user;
CREATE TRIGGER update_sys_user_update_time
    BEFORE UPDATE ON sys_user
    FOR EACH ROW
    EXECUTE FUNCTION update_update_time_column();

DROP TRIGGER IF EXISTS update_sys_role_update_time ON sys_role;
CREATE TRIGGER update_sys_role_update_time
    BEFORE UPDATE ON sys_role
    FOR EACH ROW
    EXECUTE FUNCTION update_update_time_column();

-- 默认角色
INSERT INTO sys_role (role_code, role_name, description, status) VALUES
('ADMIN', '管理员', '系统管理员，拥有所有权限', 1),
('USER', '普通用户', '普通用户，拥有基本权限', 1)
ON CONFLICT (role_code) DO UPDATE SET
    role_name = EXCLUDED.role_name,
    description = EXCLUDED.description;

-- 默认管理员 (密码: admin123)
INSERT INTO sys_user (username, password, nickname, email, role, status) VALUES
('admin', '$2b$12$enk/6WkSsHogyopFk/Gazu9EaGlJlvIMA.yT6HKSWIKPN1wd9atZm', '管理员', 'admin@example.com', 'ADMIN', 1)
ON CONFLICT (username) DO NOTHING;