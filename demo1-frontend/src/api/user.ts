import request from '@/utils/request';
import {
  ApiResult,
  PageResult,
  UserVO,
  UserQueryParams,
  UserCreateDTO,
  UserUpdateDTO,
  PasswordDTO,
} from '@/types';

export const userApi = {
  // 分页查询用户列表
  getList: (params: UserQueryParams) => {
    return request.get<ApiResult<PageResult<UserVO>>>('/users', { params });
  },

  // 获取用户详情
  getById: (id: number) => {
    return request.get<ApiResult<UserVO>>(`/users/${id}`);
  },

  // 创建用户
  create: (data: UserCreateDTO) => {
    return request.post<ApiResult<UserVO>>('/users', data);
  },

  // 更新用户
  update: (id: number, data: UserUpdateDTO) => {
    return request.put<ApiResult<UserVO>>(`/users/${id}`, data);
  },

  // 删除用户
  delete: (id: number) => {
    return request.delete<ApiResult<void>>(`/users/${id}`);
  },

  // 修改用户状态
  updateStatus: (id: number, status: number) => {
    return request.put<ApiResult<void>>(`/users/${id}/status`, { status });
  },

  // 获取当前登录用户信息
  getProfile: () => {
    return request.get<ApiResult<UserVO>>('/users/profile');
  },

  // 更新当前登录用户信息
  updateProfile: (data: UserUpdateDTO) => {
    return request.put<ApiResult<UserVO>>('/users/profile', data);
  },

  // 修改当前登录用户密码
  updatePassword: (data: PasswordDTO) => {
    return request.put<ApiResult<void>>('/users/password', data);
  },
};
