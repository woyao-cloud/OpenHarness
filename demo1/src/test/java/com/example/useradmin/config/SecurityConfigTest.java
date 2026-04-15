package com.example.useradmin.config;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.security.crypto.password.PasswordEncoder;

import static org.junit.jupiter.api.Assertions.*;

class SecurityConfigTest {

    @Test
    @DisplayName("密码编码器 - 正确编码密码")
    void passwordEncoder_EncodePassword() {
        PasswordEncoder encoder = new SecurityConfig(null, null).passwordEncoder();
        
        String rawPassword = "password123";
        String encodedPassword = encoder.encode(rawPassword);
        
        assertNotNull(encodedPassword);
        assertNotEquals(rawPassword, encodedPassword);
        assertTrue(encodedPassword.startsWith("$2a$"));
    }

    @Test
    @DisplayName("密码编码器 - 正确匹配密码")
    void passwordEncoder_MatchesPassword() {
        PasswordEncoder encoder = new SecurityConfig(null, null).passwordEncoder();
        
        String rawPassword = "password123";
        String encodedPassword = encoder.encode(rawPassword);
        
        assertTrue(encoder.matches(rawPassword, encodedPassword));
    }

    @Test
    @DisplayName("密码编码器 - 错误密码不匹配")
    void passwordEncoder_DoesNotMatchWrongPassword() {
        PasswordEncoder encoder = new SecurityConfig(null, null).passwordEncoder();
        
        String rawPassword = "password123";
        String encodedPassword = encoder.encode(rawPassword);
        
        assertFalse(encoder.matches("wrongpassword", encodedPassword));
    }

    @Test
    @DisplayName("密码编码器 - 不同密码生成不同哈希")
    void passwordEncoder_DifferentPasswordsDifferentHashes() {
        PasswordEncoder encoder = new SecurityConfig(null, null).passwordEncoder();
        
        String encoded1 = encoder.encode("password1");
        String encoded2 = encoder.encode("password2");
        
        assertNotEquals(encoded1, encoded2);
    }

    @Test
    @DisplayName("密码编码器 - 相同密码生成不同哈希(盐值不同)")
    void passwordEncoder_SamePasswordDifferentHashes() {
        PasswordEncoder encoder = new SecurityConfig(null, null).passwordEncoder();
        
        String encoded1 = encoder.encode("password");
        String encoded2 = encoder.encode("password");
        
        assertNotEquals(encoded1, encoded2);
        assertTrue(encoder.matches("password", encoded1));
        assertTrue(encoder.matches("password", encoded2));
    }
}
