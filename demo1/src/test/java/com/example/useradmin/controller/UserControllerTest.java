package com.example.useradmin.controller;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.example.useradmin.dto.PasswordDTO;
import com.example.useradmin.dto.UserCreateDTO;
import com.example.useradmin.dto.UserUpdateDTO;
import com.example.useradmin.service.UserService;
import com.example.useradmin.vo.UserVO;
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
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class UserControllerTest {

    @Mock
    private UserService userService;

    @InjectMocks
    private UserController userController;

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
    void getUserPage_Success() {
        Page<UserVO> page = new Page<>(1, 10);
        page.setRecords(Arrays.asList(userVO));
        page.setTotal(1);

        when(userService.getUserPage(1L, 10L, null)).thenReturn(page);

        var result = userController.getUserPage(1L, 10L, null);

        assertNotNull(result);
        assertEquals(200, result.getCode());

        verify(userService).getUserPage(1L, 10L, null);
    }

    @Test
    @DisplayName("分页查询用户列表 - 带关键词")
    void getUserPage_WithKeyword() {
        Page<UserVO> page = new Page<>(1, 10);
        page.setRecords(Arrays.asList(userVO));
        page.setTotal(1);

        when(userService.getUserPage(1L, 10L, "test")).thenReturn(page);

        var result = userController.getUserPage(1L, 10L, "test");

        assertNotNull(result);
        assertEquals(200, result.getCode());

        verify(userService).getUserPage(1L, 10L, "test");
    }

    @Test
    @DisplayName("根据ID获取用户 - 成功")
    void getUserById_Success() {
        when(userService.getUserById(1L)).thenReturn(userVO);

        var result = userController.getUserById(1L);

        assertNotNull(result);
        assertEquals(200, result.getCode());

        verify(userService).getUserById(1L);
    }

    @Test
    @DisplayName("创建用户 - 成功")
    void createUser_Success() {
        when(userService.createUser(any(UserCreateDTO.class))).thenReturn(userVO);

        var result = userController.createUser(createDTO);

        assertNotNull(result);
        assertEquals(200, result.getCode());

        verify(userService).createUser(any(UserCreateDTO.class));
    }

    @Test
    @DisplayName("更新用户 - 成功")
    void updateUser_Success() {
        when(userService.updateUser(eq(1L), any(UserUpdateDTO.class))).thenReturn(userVO);

        var result = userController.updateUser(1L, updateDTO);

        assertNotNull(result);
        assertEquals(200, result.getCode());

        verify(userService).updateUser(eq(1L), any(UserUpdateDTO.class));
    }

    @Test
    @DisplayName("删除用户 - 成功")
    void deleteUser_Success() {
        doNothing().when(userService).deleteUser(1L);

        var result = userController.deleteUser(1L);

        assertNotNull(result);
        assertEquals(200, result.getCode());

        verify(userService).deleteUser(1L);
    }

    @Test
    @DisplayName("更新用户状态 - 成功")
    void updateUserStatus_Success() {
        doNothing().when(userService).updateUserStatus(1L, 0);

        var result = userController.updateUserStatus(1L, Map.of("status", 0));

        assertNotNull(result);
        assertEquals(200, result.getCode());

        verify(userService).updateUserStatus(1L, 0);
    }

    @Test
    @DisplayName("获取当前用户 - 成功")
    void getCurrentUser_Success() {
        when(userService.getCurrentUser()).thenReturn(userVO);

        var result = userController.getCurrentUser();

        assertNotNull(result);
        assertEquals(200, result.getCode());

        verify(userService).getCurrentUser();
    }

    @Test
    @DisplayName("更新当前用户 - 成功")
    void updateCurrentUser_Success() {
        when(userService.updateCurrentUser(any(UserUpdateDTO.class))).thenReturn(userVO);

        var result = userController.updateCurrentUser(updateDTO);

        assertNotNull(result);
        assertEquals(200, result.getCode());

        verify(userService).updateCurrentUser(any(UserUpdateDTO.class));
    }

    @Test
    @DisplayName("修改密码 - 成功")
    void updatePassword_Success() {
        doNothing().when(userService).updatePassword(any(PasswordDTO.class));

        var result = userController.updatePassword(passwordDTO);

        assertNotNull(result);
        assertEquals(200, result.getCode());

        verify(userService).updatePassword(any(PasswordDTO.class));
    }
}
