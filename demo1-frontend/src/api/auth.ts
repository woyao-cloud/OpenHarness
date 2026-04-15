import request from '@/utils/request';
import { ApiResult, LoginDTO, LoginVO, RegisterDTO } from '@/types';

export const authApi = {
  // 登录
  login: (data: LoginDTO) => {
    return request.post<ApiResult<LoginVO>>('/auth/login', data);
  },

  // 注册
  register: (data: RegisterDTO) => {
    return request.post<ApiResult<void>>('/auth/register', data);
  },

  // 刷新Token
  refresh: (refreshToken: string) => {
    return request.post<ApiResult<LoginVO>>('/auth/refresh', { refreshToken });
  },

  // 登出
  logout: () => {
    return request.post<ApiResult<void>>('/auth/logout');
  },
};
