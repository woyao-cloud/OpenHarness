package com.example.useradmin.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.example.useradmin.common.exception.BusinessException;
import com.example.useradmin.dto.RoleCreateDTO;
import com.example.useradmin.dto.RoleQueryDTO;
import com.example.useradmin.dto.RoleUpdateDTO;
import com.example.useradmin.entity.Role;
import com.example.useradmin.mapper.RoleMapper;
import com.example.useradmin.vo.RoleVO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class RoleServiceImplTest {

    @Mock
    private RoleMapper roleMapper;

    @Spy
    @InjectMocks
    private RoleServiceImpl roleService;

    private Role testRole;
    private RoleCreateDTO createDTO;
    private RoleUpdateDTO updateDTO;
    private RoleQueryDTO queryDTO;

    @BeforeEach
    void setUp() {
        testRole = new Role();
        testRole.setId(1L);
        testRole.setRoleCode("ADMIN");
        testRole.setRoleName("管理员");
        testRole.setDescription("系统管理员角色");
        testRole.setStatus(1);

        createDTO = new RoleCreateDTO();
        createDTO.setRoleCode("USER");
        createDTO.setRoleName("普通用户");
        createDTO.setDescription("普通用户角色");
        createDTO.setStatus(1);

        updateDTO = new RoleUpdateDTO();
        updateDTO.setRoleName("更新后的角色名");
        updateDTO.setDescription("更新后的描述");
        updateDTO.setStatus(1);

        queryDTO = new RoleQueryDTO();
        queryDTO.setCurrent(1L);
        queryDTO.setSize(10L);
    }

    @Test
    @DisplayName("分页查询角色列表 - 无条件")
    void getRolePage_NoCondition() {
        Page<Role> page = new Page<>(1, 10);
        page.setRecords(Arrays.asList(testRole));
        page.setTotal(1);

        when(roleMapper.selectPage(any(), any(LambdaQueryWrapper.class))).thenReturn(page);

        IPage<RoleVO> result = roleService.getRolePage(queryDTO);

        assertNotNull(result);
        verify(roleMapper).selectPage(any(), any(LambdaQueryWrapper.class));
    }

    @Test
    @DisplayName("分页查询角色列表 - 有关键词")
    void getRolePage_WithKeyword() {
        queryDTO.setKeyword("ADMIN");
        Page<Role> page = new Page<>(1, 10);
        page.setRecords(Arrays.asList(testRole));
        page.setTotal(1);

        when(roleMapper.selectPage(any(), any(LambdaQueryWrapper.class))).thenReturn(page);

        IPage<RoleVO> result = roleService.getRolePage(queryDTO);

        assertNotNull(result);
        verify(roleMapper).selectPage(any(), any(LambdaQueryWrapper.class));
    }

    @Test
    @DisplayName("分页查询角色列表 - 有状态筛选")
    void getRolePage_WithStatus() {
        queryDTO.setStatus(1);
        Page<Role> page = new Page<>(1, 10);
        page.setRecords(Arrays.asList(testRole));
        page.setTotal(1);

        when(roleMapper.selectPage(any(), any(LambdaQueryWrapper.class))).thenReturn(page);

        IPage<RoleVO> result = roleService.getRolePage(queryDTO);

        assertNotNull(result);
        verify(roleMapper).selectPage(any(), any(LambdaQueryWrapper.class));
    }

    @Test
    @DisplayName("分页查询角色列表 - 有关键词和状态")
    void getRolePage_WithKeywordAndStatus() {
        queryDTO.setKeyword("ADMIN");
        queryDTO.setStatus(1);
        Page<Role> page = new Page<>(1, 10);
        page.setRecords(Arrays.asList(testRole));
        page.setTotal(1);

        when(roleMapper.selectPage(any(), any(LambdaQueryWrapper.class))).thenReturn(page);

        IPage<RoleVO> result = roleService.getRolePage(queryDTO);

        assertNotNull(result);
        verify(roleMapper).selectPage(any(), any(LambdaQueryWrapper.class));
    }

    @Test
    @DisplayName("根据ID获取角色 - 成功")
    void getRoleById_Success() {
        doReturn(testRole).when(roleService).getById(1L);

        RoleVO result = roleService.getRoleById(1L);

        assertNotNull(result);
        assertEquals("ADMIN", result.getRoleCode());
        assertEquals("管理员", result.getRoleName());
    }

    @Test
    @DisplayName("根据ID获取角色 - 角色不存在")
    void getRoleById_NotFound() {
        doReturn(null).when(roleService).getById(999L);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> roleService.getRoleById(999L));

        assertEquals("角色不存在", exception.getMessage());
    }

    @Test
    @DisplayName("创建角色 - 成功")
    void createRole_Success() {
        when(roleMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(0L);

        RoleVO result = roleService.createRole(createDTO);

        assertNotNull(result);
        verify(roleMapper).insert(any(Role.class));
    }

    @Test
    @DisplayName("创建角色 - 角色编码已存在")
    void createRole_CodeExists() {
        when(roleMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(1L);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> roleService.createRole(createDTO));

        assertEquals("角色编码已存在", exception.getMessage());
        verify(roleMapper, never()).insert(any(Role.class));
    }

    @Test
    @DisplayName("更新角色 - 成功")
    void updateRole_Success() {
        doReturn(testRole).when(roleService).getById(1L);
        doReturn(true).when(roleService).updateById(any(Role.class));

        RoleVO result = roleService.updateRole(1L, updateDTO);

        assertNotNull(result);
        verify(roleService).updateById(any(Role.class));
    }

    @Test
    @DisplayName("更新角色 - 角色不存在")
    void updateRole_NotFound() {
        doReturn(null).when(roleService).getById(999L);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> roleService.updateRole(999L, updateDTO));

        assertEquals("角色不存在", exception.getMessage());
    }

    @Test
    @DisplayName("删除角色 - 成功")
    void deleteRole_Success() {
        doReturn(true).when(roleService).removeById(1L);

        assertDoesNotThrow(() -> roleService.deleteRole(1L));
    }

    @Test
    @DisplayName("删除角色 - 角色不存在")
    void deleteRole_NotFound() {
        doReturn(false).when(roleService).removeById(999L);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> roleService.deleteRole(999L));

        assertEquals("角色不存在", exception.getMessage());
    }

    @Test
    @DisplayName("更新角色状态 - 成功")
    void updateRoleStatus_Success() {
        doReturn(testRole).when(roleService).getById(1L);
        doReturn(true).when(roleService).updateById(any(Role.class));

        roleService.updateRoleStatus(1L, 0);

        assertEquals(0, testRole.getStatus());
    }

    @Test
    @DisplayName("更新角色状态 - 角色不存在")
    void updateRoleStatus_NotFound() {
        doReturn(null).when(roleService).getById(999L);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> roleService.updateRoleStatus(999L, 0));

        assertEquals("角色不存在", exception.getMessage());
    }

    @Test
    @DisplayName("获取所有有效角色列表")
    void getAllActiveRoles_Success() {
        Role role1 = new Role();
        role1.setId(1L);
        role1.setRoleCode("ADMIN");
        role1.setRoleName("管理员");
        role1.setStatus(1);

        Role role2 = new Role();
        role2.setId(2L);
        role2.setRoleCode("USER");
        role2.setRoleName("普通用户");
        role2.setStatus(1);

        when(roleMapper.selectAllActiveRoles()).thenReturn(Arrays.asList(role1, role2));

        List<RoleVO> result = roleService.getAllActiveRoles();

        assertNotNull(result);
        assertEquals(2, result.size());
        assertEquals("ADMIN", result.get(0).getRoleCode());
        assertEquals("USER", result.get(1).getRoleCode());
    }

    @Test
    @DisplayName("获取所有有效角色列表 - 空列表")
    void getAllActiveRoles_Empty() {
        when(roleMapper.selectAllActiveRoles()).thenReturn(Collections.emptyList());

        List<RoleVO> result = roleService.getAllActiveRoles();

        assertNotNull(result);
        assertTrue(result.isEmpty());
    }
}
