package com.example.useradmin.service;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.example.useradmin.dto.RoleCreateDTO;
import com.example.useradmin.dto.RoleQueryDTO;
import com.example.useradmin.dto.RoleUpdateDTO;
import com.example.useradmin.vo.RoleVO;

import java.util.List;

public interface RoleService {

    IPage<RoleVO> getRolePage(RoleQueryDTO queryDTO);

    RoleVO getRoleById(Long id);

    RoleVO createRole(RoleCreateDTO dto);

    RoleVO updateRole(Long id, RoleUpdateDTO dto);

    void deleteRole(Long id);

    void updateRoleStatus(Long id, Integer status);

    List<RoleVO> getAllActiveRoles();
}
