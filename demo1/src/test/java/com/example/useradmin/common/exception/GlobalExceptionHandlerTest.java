package com.example.useradmin.common.exception;

import com.example.useradmin.common.Result;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.BindingResult;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;

import java.util.Collections;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class GlobalExceptionHandlerTest {

    private final GlobalExceptionHandler handler = new GlobalExceptionHandler();

    @Test
    @DisplayName("处理业务异常")
    void handleBusinessException() {
        BusinessException exception = new BusinessException("业务错误");

        Result<?> result = handler.handleBusinessException(exception);

        assertNotNull(result);
        assertEquals(500, result.getCode());
        assertEquals("业务错误", result.getMessage());
    }

    @Test
    @DisplayName("处理业务异常 - 带状态码")
    void handleBusinessException_WithCode() {
        BusinessException exception = new BusinessException(401, "未授权");

        Result<?> result = handler.handleBusinessException(exception);

        assertNotNull(result);
        assertEquals(401, result.getCode());
        assertEquals("未授权", result.getMessage());
    }

    @Test
    @DisplayName("处理参数校验异常")
    void handleValidationException() {
        MethodArgumentNotValidException exception = mock(MethodArgumentNotValidException.class);
        BindingResult bindingResult = mock(BindingResult.class);
        FieldError fieldError = new FieldError("object", "field", "字段不能为空");

        when(exception.getBindingResult()).thenReturn(bindingResult);
        when(bindingResult.getFieldError()).thenReturn(fieldError);

        Result<?> result = handler.handleValidationException(exception);

        assertNotNull(result);
        assertEquals(400, result.getCode());
        assertTrue(result.getMessage().contains("字段不能为空"));
    }

    @Test
    @DisplayName("处理通用异常")
    void handleException() {
        Exception exception = new RuntimeException("系统错误");

        Result<?> result = handler.handleException(exception);

        assertNotNull(result);
        assertEquals(500, result.getCode());
        assertEquals("系统错误", result.getMessage());
    }
}
