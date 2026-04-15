package com.example.useradmin.controller;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.example.useradmin.dto.PasswordDTO;
import com.example.useradmin.dto.UserCreateDTO;
import com.example.useradmin.dto.UserUpdateDTO;
import com.example.useradmin.service.UserService;
import com.example.useradmin.vo.UserVO;
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

@WebMvcTest(UserController.class)
@AutoConfigureMockMvc(addFilters = false)
class UserControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private UserService userService;

    private UserVO userVO;
    private UserCreateDTO createDTO;
    private UserUpdateDTO updateDTO;
    private PasswordDTO passwordDTO;

    @BeforeEach
    void setUp() {
        userVO = new UserVO();
        userVO.setId(1L);
        userVO.setUsername("testuser");
        userVO.setNickname("Test User");
        userVO.setEmail("test@example.com");
        userVO.setPhone("13800138000");
        userVO.setStatus(1);
        userVO.setRoles(Arrays.asList("USER"));

        createDTO = new UserCreateDTO();
        createDTO.setUsername("newuser");
        createDTO.setPassword("password123");
        createDTO.setNickname("New User");
        createDTO.setEmail("new@example.com");
        createDTO.setPhone("13900139000");
        createDTO.setStatus(1);
        createDTO.setRoleIds(Arrays.asList(1L));

        updateDTO = new UserUpdateDTO();
        updateDTO.setNickname("Updated User");
        updateDTO.setEmail("updated@example.com");
        updateDTO.setPhone("13700137000");
        updateDTO.setRoleIds(Arrays.asList(1L));

        passwordDTO = new PasswordDTO();
        passwordDTO.setOldPassword("oldPassword");
        passwordDTO.setNewPassword("newPassword123");
    }

    @Test
    @DisplayName("分页查询用户列表 - 成功")
    void getUserPage_Success() throws Exception {
        Page<UserVO> page = new Page<>(1, 10);
        page.setRecords(Arrays.asList(userVO));
        page.setTotal(1);

        when(userService.getUserPage(1L, 10L, null)).thenReturn(page);

        mockMvc.perform(get("/api/users")
                        .param("current", "1")
                        .param("size", "10"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.data.records").isArray());

        verify(userService).getUserPage(1L, 10L, null);
    }

    @Test
    @DisplayName("分页查询用户列表 - 带关键词")
    void getUserPage_WithKeyword() throws Exception {
        Page<UserVO> page = new Page<>(1, 10);
        page.setRecords(Arrays.asList(userVO));
        page.setTotal(1);

        when(userService.getUserPage(1L, 10L, "test")).thenReturn(page);

        mockMvc.perform(get("/api/users")
                        .param("current", "1")
                        .param("size", "10")
                        .param("keyword", "test"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200));

        verify(userService).getUserPage(1L, 10L, "test");
    }

    @Test
    @DisplayName("根据ID获取用户 - 成功")
    void getUserById_Success() throws Exception {
        when(userService.getUserById(1L)).thenReturn(userVO);

        mockMvc.perform(get("/api/users/1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.data.username").value("testuser"));

        verify(userService).getUserById(1L);
    }

    @Test
    @DisplayName("创建用户 - 成功")
    void createUser_Success() throws Exception {
        when(userService.createUser(any(UserCreateDTO.class))).thenReturn(userVO);

        mockMvc.perform(post("/api/users")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(createDTO)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.data.username").value("testuser"));

        verify(userService).createUser(any(UserCreateDTO.class));
    }

    @Test
    @DisplayName("更新用户 - 成功")
    void updateUser_Success() throws Exception {
        when(userService.updateUser(eq(1L), any(UserUpdateDTO.class))).thenReturn(userVO);

        mockMvc.perform(put("/api/users/1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(updateDTO)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200));

        verify(userService).updateUser(eq(1L), any(UserUpdateDTO.class));
    }

    @Test
    @DisplayName("删除用户 - 成功")
    void deleteUser_Success() throws Exception {
        doNothing().when(userService).deleteUser(1L);

        mockMvc.perform(delete("/api/users/1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200));

        verify(userService).deleteUser(1L);
    }

    @Test
    @DisplayName("更新用户状态 - 成功")
    void updateUserStatus_Success() throws Exception {
        doNothing().when(userService).updateUserStatus(1L, 0);

        mockMvc.perform(put("/api/users/1/status")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"status\":0}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200));

        verify(userService).updateUserStatus(1L, 0);
    }

    @Test
    @DisplayName("获取当前用户 - 成功")
    void getCurrentUser_Success() throws Exception {
        when(userService.getCurrentUser()).thenReturn(userVO);

        mockMvc.perform(get("/api/users/me"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.data.username").value("testuser"));

        verify(userService).getCurrentUser();
    }

    @Test
    @DisplayName("更新当前用户 - 成功")
    void updateCurrentUser_Success() throws Exception {
        when(userService.updateCurrentUser(any(UserUpdateDTO.class))).thenReturn(userVO);

        mockMvc.perform(put("/api/users/me")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(updateDTO)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200));

        verify(userService).updateCurrentUser(any(UserUpdateDTO.class));
    }

    @Test
    @DisplayName("修改密码 - 成功")
    void updatePassword_Success() throws Exception {
        doNothing().when(userService).updatePassword(any(PasswordDTO.class));

        mockMvc.perform(put("/api/users/me/password")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(passwordDTO)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200));

        verify(userService).updatePassword(any(PasswordDTO.class));
    }
}
