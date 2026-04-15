-- 用户管理后台数据库脚本 (PostgreSQL 版本)

-- 创建数据库（在 PostgreSQL 中通常需要在外部创建数据库）
-- CREATE DATABASE user_admin WITH ENCODING = 'UTF8' LC_COLLATE = 'en_US.UTF-8' LC_CTYPE = 'en_US.UTF-8';

-- 切换到目标数据库（在初始化脚本中不需要，连接时指定）
-- \c user_admin;

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

-- 添加注释
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

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_username ON sys_user(username);
CREATE INDEX IF NOT EXISTS idx_status ON sys_user(status);

-- 创建更新时间自动更新触发器
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

-- 插入默认管理员账号 (密码: admin123)
INSERT INTO sys_user (username, password, nickname, email, role, status) VALUES 
('admin', '$2a$10$N.zmdr9k7uOCQb376NoUnuTJ8iAt6Z5EHsM8lE9lBOsl7iAt6Z5EO', '管理员', 'admin@example.com', 'ADMIN', 1)
ON CONFLICT (username) DO NOTHING;
