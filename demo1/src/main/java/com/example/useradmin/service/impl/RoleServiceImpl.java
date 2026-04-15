package com.example.useradmin.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.example.useradmin.common.exception.BusinessException;
import com.example.useradmin.dto.RoleCreateDTO;
import com.example.useradmin.dto.RoleQueryDTO;
import com.example.useradmin.dto.RoleUpdateDTO;
import com.example.useradmin.entity.Role;
import com.example.useradmin.mapper.RoleMapper;
import com.example.useradmin.service.RoleService;
import com.example.useradmin.vo.RoleVO;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.BeanUtils;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.List;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class RoleServiceImpl extends ServiceImpl<RoleMapper, Role> implements RoleService {

    private final RoleMapper roleMapper;

    @Override
    public IPage<RoleVO> getRolePage(RoleQueryDTO queryDTO) {
        Page<Role> page = new Page<>(queryDTO.getCurrent(), queryDTO.getSize());
        LambdaQueryWrapper<Role> wrapper = new LambdaQueryWrapper<>();

        if (StringUtils.hasText(queryDTO.getKeyword())) {
            wrapper.and(w -> w.like(Role::getRoleCode, queryDTO.getKeyword())
                    .or()
                    .like(Role::getRoleName, queryDTO.getKeyword()));
        }

        if (queryDTO.getStatus() != null) {
            wrapper.eq(Role::getStatus, queryDTO.getStatus());
        }

        wrapper.orderByAsc(Role::getRoleCode);

        IPage<Role> rolePage = roleMapper.selectPage(page, wrapper);
        return rolePage.convert(this::convertToVO);
    }

    @Override
    public RoleVO getRoleById(Long id) {
        Role role = getById(id);
        if (role == null) {
            throw new BusinessException("角色不存在");
        }
        return convertToVO(role);
    }

    @Override
    public RoleVO createRole(RoleCreateDTO dto) {
        // 检查角色编码是否已存在
        LambdaQueryWrapper<Role> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(Role::getRoleCode, dto.getRoleCode());
        if (roleMapper.selectCount(wrapper) > 0) {
            throw new BusinessException("角色编码已存在");
        }

        Role role = new Role();
        BeanUtils.copyProperties(dto, role);
        roleMapper.insert(role);

        return convertToVO(role);
    }

    @Override
    public RoleVO updateRole(Long id, RoleUpdateDTO dto) {
        Role role = getById(id);
        if (role == null) {
            throw new BusinessException("角色不存在");
        }

        BeanUtils.copyProperties(dto, role);
        updateById(role);

        return convertToVO(role);
    }

    @Override
    public void deleteRole(Long id) {
        if (!removeById(id)) {
            throw new BusinessException("角色不存在");
        }
    }

    @Override
    public void updateRoleStatus(Long id, Integer status) {
        Role role = getById(id);
        if (role == null) {
            throw new BusinessException("角色不存在");
        }

        role.setStatus(status);
        updateById(role);
    }

    @Override
    public List<RoleVO> getAllActiveRoles() {
        List<Role> roles = roleMapper.selectAllActiveRoles();
        return roles.stream()
                .map(this::convertToVO)
                .collect(Collectors.toList());
    }

    private RoleVO convertToVO(Role role) {
        RoleVO vo = new RoleVO();
        BeanUtils.copyProperties(role, vo);
        return vo;
    }
}
