package com.example.useradmin.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.example.useradmin.common.exception.BusinessException;
import com.example.useradmin.dto.PasswordDTO;
import com.example.useradmin.dto.UserCreateDTO;
import com.example.useradmin.dto.UserUpdateDTO;
import com.example.useradmin.entity.User;
import com.example.useradmin.entity.UserRole;
import com.example.useradmin.mapper.UserMapper;
import com.example.useradmin.mapper.UserRoleMapper;
import com.example.useradmin.vo.UserVO;
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
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.crypto.password.PasswordEncoder;

import java.util.Arrays;
import java.util.Collections;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class UserServiceImplTest {

    @Mock
    private UserMapper userMapper;

    @Mock
    private UserRoleMapper userRoleMapper;

    @Mock
    private PasswordEncoder passwordEncoder;

    @Mock
    private Authentication authentication;

    @Mock
    private SecurityContext securityContext;

    @Spy
    @InjectMocks
    private UserServiceImpl userService;

    private User testUser;
    private UserCreateDTO createDTO;
    private UserUpdateDTO updateDTO;
    private PasswordDTO passwordDTO;

    @BeforeEach
    void setUp() {
        testUser = new User();
        testUser.setId(1L);
        testUser.setUsername("testuser");
        testUser.setPassword("encodedPassword");
        testUser.setNickname("Test User");
        testUser.setEmail("test@example.com");
        testUser.setPhone("13800138000");
        testUser.setStatus(1);

        createDTO = new UserCreateDTO();
        createDTO.setUsername("newuser");
        createDTO.setPassword("password");
        createDTO.setNickname("New User");
        createDTO.setEmail("new@example.com");
        createDTO.setPhone("13900139000");
        createDTO.setStatus(1);
        createDTO.setRoleIds(Arrays.asList(1L, 2L));

        updateDTO = new UserUpdateDTO();
        updateDTO.setNickname("Updated User");
        updateDTO.setEmail("updated@example.com");
        updateDTO.setPhone("13700137000");
        updateDTO.setRoleIds(Arrays.asList(1L));

        passwordDTO = new PasswordDTO();
        passwordDTO.setOldPassword("oldPassword");
        passwordDTO.setNewPassword("newPassword");
    }

    @Test
    @DisplayName("分页查询用户列表 - 有关键词")
    void getUserPage_WithKeyword() {
        Page<User> page = new Page<>(1, 10);
        page.setRecords(Arrays.asList(testUser));
        page.setTotal(1);

        when(userMapper.selectPage(any(), any(LambdaQueryWrapper.class))).thenReturn(page);
        when(userMapper.selectRoleCodesByUserId(any())).thenReturn(Arrays.asList("USER"));

        IPage<UserVO> result = userService.getUserPage(1L, 10L, "test");

        assertNotNull(result);
        verify(userMapper).selectPage(any(), any(LambdaQueryWrapper.class));
    }

    @Test
    @DisplayName("分页查询用户列表 - 无关键词")
    void getUserPage_WithoutKeyword() {
        Page<User> page = new Page<>(1, 10);
        page.setRecords(Arrays.asList(testUser));
        page.setTotal(1);

        when(userMapper.selectPage(any(), any(LambdaQueryWrapper.class))).thenReturn(page);
        when(userMapper.selectRoleCodesByUserId(any())).thenReturn(Collections.emptyList());

        IPage<UserVO> result = userService.getUserPage(1L, 10L, null);

        assertNotNull(result);
        verify(userMapper).selectPage(any(), any(LambdaQueryWrapper.class));
    }

    @Test
    @DisplayName("分页查询用户列表 - 空字符串关键词")
    void getUserPage_WithEmptyKeyword() {
        Page<User> page = new Page<>(1, 10);
        page.setRecords(Arrays.asList(testUser));
        page.setTotal(1);

        when(userMapper.selectPage(any(), any(LambdaQueryWrapper.class))).thenReturn(page);
        when(userMapper.selectRoleCodesByUserId(any())).thenReturn(Collections.emptyList());

        IPage<UserVO> result = userService.getUserPage(1L, 10L, "");

        assertNotNull(result);
        verify(userMapper).selectPage(any(), any(LambdaQueryWrapper.class));
    }

    @Test
    @DisplayName("根据ID获取用户 - 成功")
    void getUserById_Success() {
        doReturn(testUser).when(userService).getById(1L);
        when(userMapper.selectRoleCodesByUserId(1L)).thenReturn(Arrays.asList("USER"));

        UserVO result = userService.getUserById(1L);

        assertNotNull(result);
        assertEquals("testuser", result.getUsername());
        assertEquals(1, result.getRoles().size());
    }

    @Test
    @DisplayName("根据ID获取用户 - 用户不存在")
    void getUserById_NotFound() {
        doReturn(null).when(userService).getById(999L);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> userService.getUserById(999L));

        assertEquals("用户不存在", exception.getMessage());
    }

    @Test
    @DisplayName("创建用户 - 成功")
    void createUser_Success() {
        when(userMapper.selectByUsername("newuser")).thenReturn(null);
        when(passwordEncoder.encode("password")).thenReturn("encodedPassword");

        UserVO result = userService.createUser(createDTO);

        verify(userMapper).insert(any(User.class));
        verify(userRoleMapper, times(2)).insert(any(UserRole.class));
    }

    @Test
    @DisplayName("创建用户 - 成功无角色")
    void createUser_Success_NoRoles() {
        createDTO.setRoleIds(null);
        when(userMapper.selectByUsername("newuser")).thenReturn(null);
        when(passwordEncoder.encode("password")).thenReturn("encodedPassword");

        UserVO result = userService.createUser(createDTO);

        verify(userMapper).insert(any(User.class));
        verify(userRoleMapper, never()).insert(any(UserRole.class));
    }

    @Test
    @DisplayName("创建用户 - 用户名已存在")
    void createUser_UsernameExists() {
        when(userMapper.selectByUsername("newuser")).thenReturn(testUser);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> userService.createUser(createDTO));

        assertEquals("用户名已存在", exception.getMessage());
        verify(userMapper, never()).insert(any(User.class));
    }

    @Test
    @DisplayName("更新用户 - 成功")
    void updateUser_Success() {
        doReturn(testUser).when(userService).getById(1L);
        doReturn(true).when(userService).updateById(any(User.class));
        doNothing().when(userRoleMapper).deleteByUserId(1L);

        UserVO result = userService.updateUser(1L, updateDTO);

        verify(userRoleMapper).deleteByUserId(1L);
        verify(userRoleMapper).insert(any(UserRole.class));
    }

    @Test
    @DisplayName("更新用户 - 成功清空角色")
    void updateUser_Success_ClearRoles() {
        updateDTO.setRoleIds(Collections.emptyList());
        doReturn(testUser).when(userService).getById(1L);
        doReturn(true).when(userService).updateById(any(User.class));
        doNothing().when(userRoleMapper).deleteByUserId(1L);

        UserVO result = userService.updateUser(1L, updateDTO);

        verify(userRoleMapper).deleteByUserId(1L);
        verify(userRoleMapper, never()).insert(any(UserRole.class));
    }

    @Test
    @DisplayName("更新用户 - 不更新角色")
    void updateUser_Success_NoRoleUpdate() {
        updateDTO.setRoleIds(null);
        doReturn(testUser).when(userService).getById(1L);
        doReturn(true).when(userService).updateById(any(User.class));

        UserVO result = userService.updateUser(1L, updateDTO);

        verify(userRoleMapper, never()).deleteByUserId(any());
    }

    @Test
    @DisplayName("更新用户 - 用户不存在")
    void updateUser_NotFound() {
        doReturn(null).when(userService).getById(999L);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> userService.updateUser(999L, updateDTO));

        assertEquals("用户不存在", exception.getMessage());
    }

    @Test
    @DisplayName("删除用户 - 成功")
    void deleteUser_Success() {
        doReturn(true).when(userService).removeById(1L);

        assertDoesNotThrow(() -> userService.deleteUser(1L));
    }

    @Test
    @DisplayName("删除用户 - 用户不存在")
    void deleteUser_NotFound() {
        doReturn(false).when(userService).removeById(999L);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> userService.deleteUser(999L));

        assertEquals("用户不存在", exception.getMessage());
    }

    @Test
    @DisplayName("更新用户状态 - 成功")
    void updateUserStatus_Success() {
        doReturn(testUser).when(userService).getById(1L);
        doReturn(true).when(userService).updateById(any(User.class));

        userService.updateUserStatus(1L, 0);

        assertEquals(0, testUser.getStatus());
    }

    @Test
    @DisplayName("更新用户状态 - 用户不存在")
    void updateUserStatus_NotFound() {
        doReturn(null).when(userService).getById(999L);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> userService.updateUserStatus(999L, 0));

        assertEquals("用户不存在", exception.getMessage());
    }

    @Test
    @DisplayName("获取当前用户 - 成功")
    void getCurrentUser_Success() {
        when(securityContext.getAuthentication()).thenReturn(authentication);
        when(authentication.getName()).thenReturn("testuser");
        SecurityContextHolder.setContext(securityContext);
        when(userMapper.selectByUsername("testuser")).thenReturn(testUser);
        when(userMapper.selectRoleCodesByUserId(1L)).thenReturn(Arrays.asList("USER"));

        UserVO result = userService.getCurrentUser();

        assertNotNull(result);
        assertEquals("testuser", result.getUsername());
    }

    @Test
    @DisplayName("获取当前用户 - 用户不存在")
    void getCurrentUser_NotFound() {
        when(securityContext.getAuthentication()).thenReturn(authentication);
        when(authentication.getName()).thenReturn("testuser");
        SecurityContextHolder.setContext(securityContext);
        when(userMapper.selectByUsername("testuser")).thenReturn(null);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> userService.getCurrentUser());

        assertEquals("用户不存在", exception.getMessage());
    }

    @Test
    @DisplayName("更新当前用户 - 成功")
    void updateCurrentUser_Success() {
        when(securityContext.getAuthentication()).thenReturn(authentication);
        when(authentication.getName()).thenReturn("testuser");
        SecurityContextHolder.setContext(securityContext);
        when(userMapper.selectByUsername("testuser")).thenReturn(testUser);
        doReturn(true).when(userService).updateById(any(User.class));

        UserVO result = userService.updateCurrentUser(updateDTO);

        verify(userService).updateById(any(User.class));
    }

    @Test
    @DisplayName("更新当前用户 - 用户不存在")
    void updateCurrentUser_NotFound() {
        when(securityContext.getAuthentication()).thenReturn(authentication);
        when(authentication.getName()).thenReturn("testuser");
        SecurityContextHolder.setContext(securityContext);
        when(userMapper.selectByUsername("testuser")).thenReturn(null);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> userService.updateCurrentUser(updateDTO));

        assertEquals("用户不存在", exception.getMessage());
    }

    @Test
    @DisplayName("修改密码 - 成功")
    void updatePassword_Success() {
        when(securityContext.getAuthentication()).thenReturn(authentication);
        when(authentication.getName()).thenReturn("testuser");
        SecurityContextHolder.setContext(securityContext);
        when(userMapper.selectByUsername("testuser")).thenReturn(testUser);
        when(passwordEncoder.matches("oldPassword", "encodedPassword")).thenReturn(true);
        when(passwordEncoder.encode("newPassword")).thenReturn("newEncodedPassword");
        doReturn(true).when(userService).updateById(any(User.class));

        userService.updatePassword(passwordDTO);

        verify(userService).updateById(any(User.class));
    }

    @Test
    @DisplayName("修改密码 - 用户不存在")
    void updatePassword_UserNotFound() {
        when(securityContext.getAuthentication()).thenReturn(authentication);
        when(authentication.getName()).thenReturn("testuser");
        SecurityContextHolder.setContext(securityContext);
        when(userMapper.selectByUsername("testuser")).thenReturn(null);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> userService.updatePassword(passwordDTO));

        assertEquals("用户不存在", exception.getMessage());
    }

    @Test
    @DisplayName("修改密码 - 旧密码错误")
    void updatePassword_WrongOldPassword() {
        when(securityContext.getAuthentication()).thenReturn(authentication);
        when(authentication.getName()).thenReturn("testuser");
        SecurityContextHolder.setContext(securityContext);
        when(userMapper.selectByUsername("testuser")).thenReturn(testUser);
        when(passwordEncoder.matches("oldPassword", "encodedPassword")).thenReturn(false);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> userService.updatePassword(passwordDTO));

        assertEquals("旧密码错误", exception.getMessage());
    }
}
