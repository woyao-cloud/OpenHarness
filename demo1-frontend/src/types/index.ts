// 通用响应类型
export interface ApiResult<T> {
  code: number;
  message: string;
  data: T;
  timestamp: number;
}

// 分页结果
export interface PageResult<T> {
  records: T[];
  total: number;
  size: number;
  current: number;
  pages: number;
}

// 用户信息
export interface UserVO {
  id: number;
  username: string;
  nickname?: string;
  email?: string;
  phone?: string;
  avatar?: string;
  status: number;
  role: string;
  createTime: string;
  updateTime: string;
}

// 登录响应
export interface LoginVO {
  accessToken: string;
  refreshToken: string;
  expiresIn: number;
  userInfo: UserVO;
}

// 登录请求
export interface LoginDTO {
  username: string;
  password: string;
}

// 注册请求
export interface RegisterDTO {
  username: string;
  password: string;
  nickname?: string;
  email?: string;
  phone?: string;
}

// 创建用户请求
export interface UserCreateDTO {
  username: string;
  password: string;
  nickname?: string;
  email?: string;
  phone?: string;
  avatar?: string;
  status?: number;
  role?: string;
}

// 更新用户请求
export interface UserUpdateDTO {
  nickname?: string;
  email?: string;
  phone?: string;
  avatar?: string;
}

// 修改密码请求
export interface PasswordDTO {
  oldPassword: string;
  newPassword: string;
}

// 用户查询参数
export interface UserQueryParams {
  current?: number;
  size?: number;
  keyword?: string;
}
