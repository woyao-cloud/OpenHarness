package com.example.useradmin.controller;

import com.example.useradmin.dto.LoginDTO;
import com.example.useradmin.dto.RegisterDTO;
import com.example.useradmin.service.AuthService;
import com.example.useradmin.vo.LoginVO;
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
import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class AuthControllerTest {

    @Mock
    private AuthService authService;

    @InjectMocks
    private AuthController authController;

    private LoginDTO loginDTO;
    private RegisterDTO registerDTO;
    private LoginVO loginVO;

    @BeforeEach
    void setUp() {
        loginDTO = new LoginDTO();
        loginDTO.setUsername("testuser");
        loginDTO.setPassword("password");

        registerDTO = new RegisterDTO();
        registerDTO.setUsername("newuser");
        registerDTO.setPassword("password123");
        registerDTO.setNickname("New User");
        registerDTO.setEmail("new@example.com");
        registerDTO.setPhone("13800138000");

        UserVO userVO = new UserVO();
        userVO.setId(1L);
        userVO.setUsername("testuser");
        userVO.setNickname("Test User");
        userVO.setRoles(Arrays.asList("USER"));

        loginVO = new LoginVO();
        loginVO.setAccessToken("accessToken");
        loginVO.setRefreshToken("refreshToken");
        loginVO.setExpiresIn(3600L);
        loginVO.setUserInfo(userVO);
    }

    @Test
    @DisplayName("登录接口 - 成功")
    void login_Success() {
        when(authService.login(any(LoginDTO.class))).thenReturn(loginVO);

        var result = authController.login(loginDTO);

        assertNotNull(result);
        assertEquals(200, result.getCode());
        assertNotNull(result.getData());
        assertEquals("accessToken", result.getData().getAccessToken());

        verify(authService).login(any(LoginDTO.class));
    }

    @Test
    @DisplayName("注册接口 - 成功")
    void register_Success() {
        doNothing().when(authService).register(any(RegisterDTO.class));

        var result = authController.register(registerDTO);

        assertNotNull(result);
        assertEquals(200, result.getCode());

        verify(authService).register(any(RegisterDTO.class));
    }

    @Test
    @DisplayName("刷新Token接口 - 成功")
    void refreshToken_Success() {
        Map<String, String> request = new HashMap<>();
        request.put("refreshToken", "validRefreshToken");

        when(authService.refreshToken("validRefreshToken")).thenReturn(loginVO);

        var result = authController.refreshToken(request);

        assertNotNull(result);
        assertEquals(200, result.getCode());

        verify(authService).refreshToken("validRefreshToken");
    }

    @Test
    @DisplayName("登出接口 - 成功")
    void logout_Success() {
        doNothing().when(authService).logout();

        var result = authController.logout();

        assertNotNull(result);
        assertEquals(200, result.getCode());

        verify(authService).logout();
    }
}
