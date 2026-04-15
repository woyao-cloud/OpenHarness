package com.example.useradmin.controller;

import com.example.useradmin.dto.LoginDTO;
import com.example.useradmin.dto.RegisterDTO;
import com.example.useradmin.service.AuthService;
import com.example.useradmin.vo.LoginVO;
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
import java.util.HashMap;
import java.util.Map;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(AuthController.class)
@AutoConfigureMockMvc(addFilters = false)
class AuthControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private AuthService authService;

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
    void login_Success() throws Exception {
        when(authService.login(any(LoginDTO.class))).thenReturn(loginVO);

        mockMvc.perform(post("/api/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(loginDTO)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.data.accessToken").value("accessToken"))
                .andExpect(jsonPath("$.data.refreshToken").value("refreshToken"))
                .andExpect(jsonPath("$.data.userInfo.username").value("testuser"));

        verify(authService).login(any(LoginDTO.class));
    }

    @Test
    @DisplayName("注册接口 - 成功")
    void register_Success() throws Exception {
        doNothing().when(authService).register(any(RegisterDTO.class));

        mockMvc.perform(post("/api/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(registerDTO)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200));

        verify(authService).register(any(RegisterDTO.class));
    }

    @Test
    @DisplayName("刷新Token接口 - 成功")
    void refreshToken_Success() throws Exception {
        Map<String, String> request = new HashMap<>();
        request.put("refreshToken", "validRefreshToken");

        when(authService.refreshToken("validRefreshToken")).thenReturn(loginVO);

        mockMvc.perform(post("/api/auth/refresh")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.data.accessToken").value("accessToken"));

        verify(authService).refreshToken("validRefreshToken");
    }

    @Test
    @DisplayName("登出接口 - 成功")
    void logout_Success() throws Exception {
        doNothing().when(authService).logout();

        mockMvc.perform(post("/api/auth/logout"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200));

        verify(authService).logout();
    }
}
