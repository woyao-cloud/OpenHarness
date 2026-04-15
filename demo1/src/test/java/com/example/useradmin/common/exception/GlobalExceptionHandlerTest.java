package com.example.useradmin.common.exception;

import com.example.useradmin.common.Result;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.validation.BindException;
import org.springframework.validation.BindingResult;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;

import java.util.Arrays;
import java.util.Collections;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
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
        when(bindingResult.getFieldErrors()).thenReturn(Arrays.asList(fieldError));

        Result<?> result = handler.handleValidationException(exception);

        assertNotNull(result);
        assertEquals(400, result.getCode());
        assertTrue(result.getMessage().contains("字段不能为空"));
    }

    @Test
    @DisplayName("处理参数绑定异常")
    void handleBindException() {
        BindException exception = mock(BindException.class);
        FieldError fieldError = new FieldError("object", "field", "绑定错误");

        when(exception.getFieldErrors()).thenReturn(Arrays.asList(fieldError));

        Result<?> result = handler.handleBindException(exception);

        assertNotNull(result);
        assertEquals(400, result.getCode());
        assertTrue(result.getMessage().contains("绑定错误"));
    }

    @Test
    @DisplayName("处理参数绑定异常 - 多个错误")
    void handleBindException_MultipleErrors() {
        BindException exception = mock(BindException.class);
        FieldError error1 = new FieldError("object", "field1", "错误1");
        FieldError error2 = new FieldError("object", "field2", "错误2");

        when(exception.getFieldErrors()).thenReturn(Arrays.asList(error1, error2));

        Result<?> result = handler.handleBindException(exception);

        assertNotNull(result);
        assertEquals(400, result.getCode());
        assertTrue(result.getMessage().contains("错误1"));
        assertTrue(result.getMessage().contains("错误2"));
    }

    @Test
    @DisplayName("处理凭证错误异常")
    void handleBadCredentialsException() {
        BadCredentialsException exception = new BadCredentialsException("Bad credentials");

        Result<?> result = handler.handleBadCredentialsException(exception);

        assertNotNull(result);
        assertEquals(401, result.getCode());
        assertEquals("用户名或密码错误", result.getMessage());
    }

    @Test
    @DisplayName("处理访问拒绝异常")
    void handleAccessDeniedException() {
        AccessDeniedException exception = new AccessDeniedException("Access denied");

        Result<?> result = handler.handleAccessDeniedException(exception);

        assertNotNull(result);
        assertEquals(403, result.getCode());
        assertEquals("没有权限访问该资源", result.getMessage());
    }

    @Test
    @DisplayName("处理通用异常")
    void handleException() {
        Exception exception = new RuntimeException("系统错误");

        Result<?> result = handler.handleException(exception);

        assertNotNull(result);
        assertEquals(500, result.getCode());
        assertEquals("系统繁忙，请稍后重试", result.getMessage());
    }

    @Test
    @DisplayName("处理参数校验异常 - 空错误列表")
    void handleValidationException_EmptyErrors() {
        MethodArgumentNotValidException exception = mock(MethodArgumentNotValidException.class);
        BindingResult bindingResult = mock(BindingResult.class);

        when(exception.getBindingResult()).thenReturn(bindingResult);
        when(bindingResult.getFieldErrors()).thenReturn(Collections.emptyList());

        Result<?> result = handler.handleValidationException(exception);

        assertNotNull(result);
        assertEquals(400, result.getCode());
    }

    @Test
    @DisplayName("处理参数绑定异常 - 空错误列表")
    void handleBindException_EmptyErrors() {
        BindException exception = mock(BindException.class);

        when(exception.getFieldErrors()).thenReturn(Collections.emptyList());

        Result<?> result = handler.handleBindException(exception);

        assertNotNull(result);
        assertEquals(400, result.getCode());
    }
}
