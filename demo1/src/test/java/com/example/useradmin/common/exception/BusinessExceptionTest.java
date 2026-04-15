package com.example.useradmin.common.exception;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class BusinessExceptionTest {

    @Test
    @DisplayName("创建业务异常 - 仅消息")
    void create_WithMessage() {
        BusinessException exception = new BusinessException("业务错误");

        assertEquals("业务错误", exception.getMessage());
        assertEquals(500, exception.getCode());
    }

    @Test
    @DisplayName("创建业务异常 - 状态码和消息")
    void create_WithCodeAndMessage() {
        BusinessException exception = new BusinessException(401, "未授权");

        assertEquals("未授权", exception.getMessage());
        assertEquals(401, exception.getCode());
    }
}
