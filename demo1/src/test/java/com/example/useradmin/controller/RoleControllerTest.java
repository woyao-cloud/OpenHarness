package com.example.useradmin.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.example.useradmin.dto.RoleCreateDTO;
import com.example.useradmin.dto.RoleQueryDTO;
import com.example.useradmin.dto.RoleUpdateDTO;
import com.example.useradmin.service.RoleService;
import com.example.useradmin.vo.RoleVO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.util.Arrays;
import java.util.Collections;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class RoleControllerTest {

    @Mock
    private RoleService roleService;

    @InjectMocks
    private RoleController roleController;

    private RoleVO roleVO;
    private RoleCreateDTO createDTO;
    private RoleUpdateDTO updateDTO;

    @BeforeEach
    void setUp() {
        roleVO = new RoleVO();
        roleVO.setId(1L);
        roleVO.setRoleCode("ADMIN");
        roleVO.setRoleName("管理员");
        roleVO.setDescription("系统管理员角色");
        roleVO.setStatus(1);

        createDTO = new RoleCreateDTO();
        createDTO.setRoleCode("USER");
        createDTO.setRoleName("普通用户");
        createDTO.setDescription("普通用户角色");
        createDTO.setStatus(1);

        updateDTO = new RoleUpdateDTO();
        updateDTO.setRoleName("更新后的角色名");
        updateDTO.setDescription("更新后的描述");
        updateDTO.setStatus(1);
    }

    @Test
    @DisplayName("分页查询角色列表 - 成功")
    void getRolePage_Success() {
        Page<RoleVO> page = new Page<>(1, 10);
        page.setRecords(Arrays.asList(roleVO));
        page.setTotal(1);

        when(roleService.getRolePage(any(RoleQueryDTO.class))).thenReturn(page);

        var result = roleController.getRolePage(new RoleQueryDTO());

        assertNotNull(result);
        assertEquals(200, result.getCode());

        verify(roleService).getRolePage(any(RoleQueryDTO.class));
    }

    @Test
    @DisplayName("根据ID获取角色 - 成功")
    void getRoleById_Success() {
        when(roleService.getRoleById(1L)).thenReturn(roleVO);

        var result = roleController.getRoleById(1L);

        assertNotNull(result);
        assertEquals(200, result.getCode());

        verify(roleService).getRoleById(1L);
    }

    @Test
    @DisplayName("创建角色 - 成功")
    void createRole_Success() {
        when(roleService.createRole(any(RoleCreateDTO.class))).thenReturn(roleVO);

        var result = roleController.createRole(createDTO);

        assertNotNull(result);
        assertEquals(200, result.getCode());

        verify(roleService).createRole(any(RoleCreateDTO.class));
    }

    @Test
    @DisplayName("更新角色 - 成功")
    void updateRole_Success() {
        when(roleService.updateRole(eq(1L), any(RoleUpdateDTO.class))).thenReturn(roleVO);

        var result = roleController.updateRole(1L, updateDTO);

        assertNotNull(result);
        assertEquals(200, result.getCode());

        verify(roleService).updateRole(eq(1L), any(RoleUpdateDTO.class));
    }

    @Test
    @DisplayName("删除角色 - 成功")
    void deleteRole_Success() {
        doNothing().when(roleService).deleteRole(1L);

        var result = roleController.deleteRole(1L);

        assertNotNull(result);
        assertEquals(200, result.getCode());

        verify(roleService).deleteRole(1L);
    }

    @Test
    @DisplayName("更新角色状态 - 成功")
    void updateRoleStatus_Success() {
        doNothing().when(roleService).updateRoleStatus(1L, 0);

        var result = roleController.updateRoleStatus(1L, Map.of("status", 0));

        assertNotNull(result);
        assertEquals(200, result.getCode());

        verify(roleService).updateRoleStatus(1L, 0);
    }

    @Test
    @DisplayName("获取所有有效角色列表 - 成功")
    void getAllActiveRoles_Success() {
        when(roleService.getAllActiveRoles()).thenReturn(Arrays.asList(roleVO));

        var result = roleController.getAllActiveRoles();

        assertNotNull(result);
        assertEquals(200, result.getCode());

        verify(roleService).getAllActiveRoles();
    }

    @Test
    @DisplayName("获取所有有效角色列表 - 空列表")
    void getAllActiveRoles_Empty() {
        when(roleService.getAllActiveRoles()).thenReturn(Collections.emptyList());

        var result = roleController.getAllActiveRoles();

        assertNotNull(result);
        assertEquals(200, result.getCode());

        verify(roleService).getAllActiveRoles();
    }
}
