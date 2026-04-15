package com.example.useradmin.security;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.example.useradmin.entity.Role;
import com.example.useradmin.entity.User;
import com.example.useradmin.mapper.UserMapper;
import com.example.useradmin.mapper.RoleMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UsernameNotFoundException;

import java.util.Arrays;
import java.util.Collections;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class UserDetailsServiceImplTest {

    @Mock
    private UserMapper userMapper;

    @Mock
    private RoleMapper roleMapper;

    @InjectMocks
    private UserDetailsServiceImpl userDetailsService;

    private User testUser;
    private Role adminRole;
    private Role userRole;

    @BeforeEach
    void setUp() {
        testUser = new User();
        testUser.setId(1L);
        testUser.setUsername("testuser");
        testUser.setPassword("encodedPassword");
        testUser.setStatus(1);
        testUser.setDeleted(0);

        adminRole = new Role();
        adminRole.setId(1L);
        adminRole.setRoleCode("ADMIN");
        adminRole.setRoleName("管理员");
        adminRole.setStatus(1);

        userRole = new Role();
        userRole.setId(2L);
        userRole.setRoleCode("USER");
        userRole.setRoleName("普通用户");
        userRole.setStatus(1);
    }

    @Test
    @DisplayName("加载用户 - 成功")
    void loadUserByUsername_Success() {
        when(userMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testUser);
        when(roleMapper.selectRolesByUserId(1L)).thenReturn(Arrays.asList(adminRole, userRole));

        UserDetails userDetails = userDetailsService.loadUserByUsername("testuser");

        assertNotNull(userDetails);
        assertEquals("testuser", userDetails.getUsername());
        assertEquals("encodedPassword", userDetails.getPassword());
        assertEquals(2, userDetails.getAuthorities().size());

        verify(userMapper).selectOne(any(LambdaQueryWrapper.class));
        verify(roleMapper).selectRolesByUserId(1L);
    }

    @Test
    @DisplayName("加载用户 - 成功无角色")
    void loadUserByUsername_Success_NoRoles() {
        when(userMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testUser);
        when(roleMapper.selectRolesByUserId(1L)).thenReturn(Collections.emptyList());

        UserDetails userDetails = userDetailsService.loadUserByUsername("testuser");

        assertNotNull(userDetails);
        assertEquals("testuser", userDetails.getUsername());
        assertTrue(userDetails.getAuthorities().isEmpty());
    }

    @Test
    @DisplayName("加载用户 - 用户不存在")
    void loadUserByUsername_NotFound() {
        when(userMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);

        UsernameNotFoundException exception = assertThrows(UsernameNotFoundException.class,
                () -> userDetailsService.loadUserByUsername("nonexistent"));

        assertTrue(exception.getMessage().contains("nonexistent"));
    }
}
