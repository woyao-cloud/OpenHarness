package com.example.useradmin.controller;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.example.useradmin.dto.RoleCreateDTO;
import com.example.useradmin.dto.RoleQueryDTO;
import com.example.useradmin.dto.RoleUpdateDTO;
import com.example.useradmin.service.RoleService;
import com.example.useradmin.vo.RoleVO;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.util.Arrays;
import java.util.Collections;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(RoleController.class)
@AutoConfigureMockMvc(addFilters = false)
class RoleControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private RoleService roleService;

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
    void getRolePage_Success() throws Exception {
        Page<RoleVO> page = new Page<>(1, 10);
        page.setRecords(Arrays.asList(roleVO));
        page.setTotal(1);

        when(roleService.getRolePage(any(RoleQueryDTO.class))).thenReturn(page);

        mockMvc.perform(get("/api/roles")
                        .param("current", "1")
                        .param("size", "10"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.data.records").isArray());

        verify(roleService).getRolePage(any(RoleQueryDTO.class));
    }

    @Test
    @DisplayName("根据ID获取角色 - 成功")
    void getRoleById_Success() throws Exception {
        when(roleService.getRoleById(1L)).thenReturn(roleVO);

        mockMvc.perform(get("/api/roles/1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.data.roleCode").value("ADMIN"));

        verify(roleService).getRoleById(1L);
    }

    @Test
    @DisplayName("创建角色 - 成功")
    void createRole_Success() throws Exception {
        when(roleService.createRole(any(RoleCreateDTO.class))).thenReturn(roleVO);

        mockMvc.perform(post("/api/roles")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(createDTO)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.data.roleCode").value("ADMIN"));

        verify(roleService).createRole(any(RoleCreateDTO.class));
    }

    @Test
    @DisplayName("更新角色 - 成功")
    void updateRole_Success() throws Exception {
        when(roleService.updateRole(eq(1L), any(RoleUpdateDTO.class))).thenReturn(roleVO);

        mockMvc.perform(put("/api/roles/1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(updateDTO)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200));

        verify(roleService).updateRole(eq(1L), any(RoleUpdateDTO.class));
    }

    @Test
    @DisplayName("删除角色 - 成功")
    void deleteRole_Success() throws Exception {
        doNothing().when(roleService).deleteRole(1L);

        mockMvc.perform(delete("/api/roles/1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200));

        verify(roleService).deleteRole(1L);
    }

    @Test
    @DisplayName("更新角色状态 - 成功")
    void updateRoleStatus_Success() throws Exception {
        doNothing().when(roleService).updateRoleStatus(1L, 0);

        mockMvc.perform(put("/api/roles/1/status")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"status\":0}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200));

        verify(roleService).updateRoleStatus(1L, 0);
    }

    @Test
    @DisplayName("获取所有有效角色列表 - 成功")
    void getAllActiveRoles_Success() throws Exception {
        when(roleService.getAllActiveRoles()).thenReturn(Arrays.asList(roleVO));

        mockMvc.perform(get("/api/roles/all"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.data").isArray())
                .andExpect(jsonPath("$.data[0].roleCode").value("ADMIN"));

        verify(roleService).getAllActiveRoles();
    }

    @Test
    @DisplayName("获取所有有效角色列表 - 空列表")
    void getAllActiveRoles_Empty() throws Exception {
        when(roleService.getAllActiveRoles()).thenReturn(Collections.emptyList());

        mockMvc.perform(get("/api/roles/all"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.data").isEmpty());

        verify(roleService).getAllActiveRoles();
    }
}
