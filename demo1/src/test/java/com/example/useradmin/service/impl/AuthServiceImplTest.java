package com.example.useradmin.service.impl;

import com.example.useradmin.common.exception.BusinessException;
import com.example.useradmin.dto.LoginDTO;
import com.example.useradmin.dto.RegisterDTO;
import com.example.useradmin.entity.User;
import com.example.useradmin.mapper.UserMapper;
import com.example.useradmin.security.JwtTokenProvider;
import com.example.useradmin.vo.LoginVO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.crypto.password.PasswordEncoder;

import java.util.Arrays;
import java.util.Collections;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class AuthServiceImplTest {

    @Mock
    private AuthenticationManager authenticationManager;

    @Mock
    private JwtTokenProvider jwtTokenProvider;

    @Mock
    private UserMapper userMapper;

    @Mock
    private PasswordEncoder passwordEncoder;

    @Mock
    private Authentication authentication;

    @InjectMocks
    private AuthServiceImpl authService;

    private User testUser;
    private LoginDTO loginDTO;
    private RegisterDTO registerDTO;

    @BeforeEach
    void setUp() {
        SecurityContextHolder.clearContext();

        testUser = new User();
        testUser.setId(1L);
        testUser.setUsername("testuser");
        testUser.setPassword("encodedPassword");
        testUser.setNickname("Test User");
        testUser.setEmail("test@example.com");
        testUser.setPhone("13800138000");
        testUser.setStatus(1);

        loginDTO = new LoginDTO();
        loginDTO.setUsername("testuser");
        loginDTO.setPassword("password");

        registerDTO = new RegisterDTO();
        registerDTO.setUsername("newuser");
        registerDTO.setPassword("password");
        registerDTO.setNickname("New User");
        registerDTO.setEmail("new@example.com");
        registerDTO.setPhone("13900139000");
    }

    @Test
    @DisplayName("登录成功")
    void login_Success() {
        when(authenticationManager.authenticate(any(UsernamePasswordAuthenticationToken.class)))
                .thenReturn(authentication);
        when(jwtTokenProvider.generateAccessToken(any(Authentication.class)))
                .thenReturn("accessToken");
        when(jwtTokenProvider.generateRefreshToken(any(Authentication.class)))
                .thenReturn("refreshToken");
        when(jwtTokenProvider.getExpiration()).thenReturn(3600L);
        when(userMapper.selectByUsername("testuser")).thenReturn(testUser);
        when(userMapper.selectRoleCodesByUserId(1L)).thenReturn(Arrays.asList("USER", "ADMIN"));

        LoginVO result = authService.login(loginDTO);

        assertNotNull(result);
        assertEquals("accessToken", result.getAccessToken());
        assertEquals("refreshToken", result.getRefreshToken());
        assertEquals(3600L, result.getExpiresIn());
        assertNotNull(result.getUserInfo());
        assertEquals("testuser", result.getUserInfo().getUsername());
        assertEquals(2, result.getUserInfo().getRoles().size());

        verify(authenticationManager).authenticate(any(UsernamePasswordAuthenticationToken.class));
        verify(jwtTokenProvider).generateAccessToken(any(Authentication.class));
        verify(jwtTokenProvider).generateRefreshToken(any(Authentication.class));
        verify(userMapper).selectByUsername("testuser");
        verify(userMapper).selectRoleCodesByUserId(1L);
    }

    @Test
    @DisplayName("登录成功 - 用户无角色")
    void login_Success_NoRoles() {
        when(authenticationManager.authenticate(any(UsernamePasswordAuthenticationToken.class)))
                .thenReturn(authentication);
        when(jwtTokenProvider.generateAccessToken(any(Authentication.class)))
                .thenReturn("accessToken");
        when(jwtTokenProvider.generateRefreshToken(any(Authentication.class)))
                .thenReturn("refreshToken");
        when(jwtTokenProvider.getExpiration()).thenReturn(3600L);
        when(userMapper.selectByUsername("testuser")).thenReturn(testUser);
        when(userMapper.selectRoleCodesByUserId(1L)).thenReturn(Collections.emptyList());

        LoginVO result = authService.login(loginDTO);

        assertNotNull(result);
        assertNotNull(result.getUserInfo());
        assertTrue(result.getUserInfo().getRoles().isEmpty());
    }

    @Test
    @DisplayName("注册成功")
    void register_Success() {
        when(userMapper.selectByUsername("newuser")).thenReturn(null);
        when(passwordEncoder.encode("password")).thenReturn("encodedPassword");

        assertDoesNotThrow(() -> authService.register(registerDTO));

        verify(userMapper).selectByUsername("newuser");
        verify(passwordEncoder).encode("password");
        verify(userMapper).insert(any(User.class));
    }

    @Test
    @DisplayName("注册失败 - 用户名已存在")
    void register_Fail_UsernameExists() {
        when(userMapper.selectByUsername("newuser")).thenReturn(testUser);

        BusinessException exception = assertThrows(BusinessException.class, 
                () -> authService.register(registerDTO));

        assertEquals("用户名已存在", exception.getMessage());
        verify(userMapper).selectByUsername("newuser");
        verify(userMapper, never()).insert(any(User.class));
    }

    @Test
    @DisplayName("刷新Token成功")
    void refreshToken_Success() {
        String refreshToken = "validRefreshToken";
        when(jwtTokenProvider.validateToken(refreshToken)).thenReturn(true);
        when(jwtTokenProvider.isRefreshToken(refreshToken)).thenReturn(true);
        when(jwtTokenProvider.getUsernameFromToken(refreshToken)).thenReturn("testuser");
        when(jwtTokenProvider.generateAccessTokenFromUsername("testuser")).thenReturn("newAccessToken");
        when(jwtTokenProvider.getExpiration()).thenReturn(3600L);
        when(userMapper.selectByUsername("testuser")).thenReturn(testUser);
        when(userMapper.selectRoleCodesByUserId(1L)).thenReturn(Arrays.asList("USER"));

        LoginVO result = authService.refreshToken(refreshToken);

        assertNotNull(result);
        assertEquals("newAccessToken", result.getAccessToken());
        assertEquals(refreshToken, result.getRefreshToken());
        assertEquals(3600L, result.getExpiresIn());
        assertNotNull(result.getUserInfo());
    }

    @Test
    @DisplayName("刷新Token失败 - 无效Token")
    void refreshToken_Fail_InvalidToken() {
        String refreshToken = "invalidToken";
        when(jwtTokenProvider.validateToken(refreshToken)).thenReturn(false);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> authService.refreshToken(refreshToken));

        assertEquals(401, exception.getCode());
        assertEquals("无效的刷新令牌", exception.getMessage());
    }

    @Test
    @DisplayName("刷新Token失败 - 非RefreshToken")
    void refreshToken_Fail_NotRefreshToken() {
        String refreshToken = "accessToken";
        when(jwtTokenProvider.validateToken(refreshToken)).thenReturn(true);
        when(jwtTokenProvider.isRefreshToken(refreshToken)).thenReturn(false);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> authService.refreshToken(refreshToken));

        assertEquals(401, exception.getCode());
        assertEquals("无效的刷新令牌", exception.getMessage());
    }

    @Test
    @DisplayName("登出成功")
    void logout_Success() {
        SecurityContextHolder.getContext().setAuthentication(authentication);

        assertDoesNotThrow(() -> authService.logout());
        assertNull(SecurityContextHolder.getContext().getAuthentication());
    }
}
