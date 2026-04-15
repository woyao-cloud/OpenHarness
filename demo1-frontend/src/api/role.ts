import request from '@/utils/request';
import {
  ApiResult,
  PageResult,
  RoleVO,
  RoleQueryParams,
  RoleCreateDTO,
  RoleUpdateDTO,
} from '@/types';

export const roleApi = {
  // 分页查询角色列表
  getList: (params: RoleQueryParams) => {
    return request.get<ApiResult<PageResult<RoleVO>>>('/roles', { params });
  },

  // 获取角色详情
  getById: (id: number) => {
    return request.get<ApiResult<RoleVO>>(`/roles/${id}`);
  },

  // 创建角色
  create: (data: RoleCreateDTO) => {
    return request.post<ApiResult<RoleVO>>('/roles', data);
  },

  // 更新角色
  update: (id: number, data: RoleUpdateDTO) => {
    return request.put<ApiResult<RoleVO>>(`/roles/${id}`, data);
  },

  // 删除角色
  delete: (id: number) => {
    return request.delete<ApiResult<void>>(`/roles/${id}`);
  },

  // 修改角色状态
  updateStatus: (id: number, status: number) => {
    return request.put<ApiResult<void>>(`/roles/${id}/status`, { status });
  },

  // 获取所有有效角色列表
  getAllActive: () => {
    return request.get<ApiResult<RoleVO[]>>('/roles/all');
  },
};
