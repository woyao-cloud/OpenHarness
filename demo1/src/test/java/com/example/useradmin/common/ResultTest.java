package com.example.useradmin.common;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class ResultTest {

    @Test
    @DisplayName("成功结果 - 无数据")
    void success_NoData() {
        Result<Void> result = Result.success();

        assertNotNull(result);
        assertEquals(200, result.getCode());
        assertEquals("success", result.getMessage());
        assertNull(result.getData());
        assertNotNull(result.getTimestamp());
    }

    @Test
    @DisplayName("成功结果 - 有数据")
    void success_WithData() {
        String data = "test data";

        Result<String> result = Result.success(data);

        assertNotNull(result);
        assertEquals(200, result.getCode());
        assertEquals("success", result.getMessage());
        assertEquals("test data", result.getData());
        assertNotNull(result.getTimestamp());
    }

    @Test
    @DisplayName("错误结果 - 默认状态码")
    void error_DefaultCode() {
        Result<Void> result = Result.error("操作失败");

        assertNotNull(result);
        assertEquals(500, result.getCode());
        assertEquals("操作失败", result.getMessage());
        assertNull(result.getData());
    }

    @Test
    @DisplayName("错误结果 - 自定义状态码和消息")
    void error_CodeAndMessage() {
        Result<Void> result = Result.error(401, "未授权");

        assertNotNull(result);
        assertEquals(401, result.getCode());
        assertEquals("未授权", result.getMessage());
        assertNull(result.getData());
    }
}
