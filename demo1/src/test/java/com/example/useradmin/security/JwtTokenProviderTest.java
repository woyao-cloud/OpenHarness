package com.example.useradmin.security;

import io.jsonwebtoken.ExpiredJwtException;
import io.jsonwebtoken.MalformedJwtException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Collections;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class JwtTokenProviderTest {

    private JwtTokenProvider jwtTokenProvider;

    private Authentication authentication;

    @BeforeEach
    void setUp() {
        jwtTokenProvider = new JwtTokenProvider();
        ReflectionTestUtils.setField(jwtTokenProvider, "jwtSecret", "thisIsAVeryLongSecretKeyForTestingPurposesThatShouldBeAtLeast256BitsLong");
        ReflectionTestUtils.setField(jwtTokenProvider, "jwtExpiration", 3600000L);
        ReflectionTestUtils.setField(jwtTokenProvider, "refreshExpiration", 86400000L);
        jwtTokenProvider.init();

        authentication = mock(Authentication.class);
        when(authentication.getName()).thenReturn("testuser");
    }

    @Test
    @DisplayName("生成访问Token - 成功")
    void generateAccessToken_Success() {
        String token = jwtTokenProvider.generateAccessToken(authentication);

        assertNotNull(token);
        assertFalse(token.isEmpty());
    }

    @Test
    @DisplayName("生成刷新Token - 成功")
    void generateRefreshToken_Success() {
        String token = jwtTokenProvider.generateRefreshToken(authentication);

        assertNotNull(token);
        assertFalse(token.isEmpty());
    }

    @Test
    @DisplayName("从用户名生成访问Token - 成功")
    void generateAccessTokenFromUsername_Success() {
        String token = jwtTokenProvider.generateAccessTokenFromUsername("testuser");

        assertNotNull(token);
        assertFalse(token.isEmpty());
    }

    @Test
    @DisplayName("从Token获取用户名 - 成功")
    void getUsernameFromToken_Success() {
        String token = jwtTokenProvider.generateAccessToken(authentication);

        String username = jwtTokenProvider.getUsernameFromToken(token);

        assertEquals("testuser", username);
    }

    @Test
    @DisplayName("验证Token - 有效Token")
    void validateToken_ValidToken() {
        String token = jwtTokenProvider.generateAccessToken(authentication);

        boolean isValid = jwtTokenProvider.validateToken(token);

        assertTrue(isValid);
    }

    @Test
    @DisplayName("验证Token - 无效Token")
    void validateToken_InvalidToken() {
        boolean isValid = jwtTokenProvider.validateToken("invalid.token.here");

        assertFalse(isValid);
    }

    @Test
    @DisplayName("验证Token - 空Token")
    void validateToken_EmptyToken() {
        boolean isValid = jwtTokenProvider.validateToken("");

        assertFalse(isValid);
    }

    @Test
    @DisplayName("验证Token - null Token")
    void validateToken_NullToken() {
        boolean isValid = jwtTokenProvider.validateToken(null);

        assertFalse(isValid);
    }

    @Test
    @DisplayName("判断是否为刷新Token - 是刷新Token")
    void isRefreshToken_True() {
        String token = jwtTokenProvider.generateRefreshToken(authentication);

        boolean isRefresh = jwtTokenProvider.isRefreshToken(token);

        assertTrue(isRefresh);
    }

    @Test
    @DisplayName("判断是否为刷新Token - 是访问Token")
    void isRefreshToken_False() {
        String token = jwtTokenProvider.generateAccessToken(authentication);

        boolean isRefresh = jwtTokenProvider.isRefreshToken(token);

        assertFalse(isRefresh);
    }

    @Test
    @DisplayName("判断是否为刷新Token - 无效Token")
    void isRefreshToken_InvalidToken() {
        boolean isRefresh = jwtTokenProvider.isRefreshToken("invalid.token.here");

        assertFalse(isRefresh);
    }

    @Test
    @DisplayName("获取过期时间 - 成功")
    void getExpiration_Success() {
        long expiration = jwtTokenProvider.getExpiration();

        assertEquals(3600L, expiration);
    }
}
