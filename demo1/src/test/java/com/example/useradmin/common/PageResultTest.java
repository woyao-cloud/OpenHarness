package com.example.useradmin.common;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.Collections;

import static org.junit.jupiter.api.Assertions.*;

class PageResultTest {

    @Test
    @DisplayName("从IPage创建分页结果")
    void of_Success() {
        Page<String> page = new Page<>(1, 10);
        page.setRecords(Arrays.asList("item1", "item2"));
        page.setTotal(100);

        PageResult<String> result = PageResult.of(page);

        assertNotNull(result);
        assertEquals(Arrays.asList("item1", "item2"), result.getRecords());
        assertEquals(100L, result.getTotal());
        assertEquals(1L, result.getCurrent());
        assertEquals(10L, result.getSize());
        assertEquals(10, result.getPages());
    }

    @Test
    @DisplayName("从空IPage创建分页结果")
    void of_EmptyPage() {
        Page<String> page = new Page<>(1, 10);
        page.setRecords(Collections.emptyList());
        page.setTotal(0);

        PageResult<String> result = PageResult.of(page);

        assertNotNull(result);
        assertTrue(result.getRecords().isEmpty());
        assertEquals(0L, result.getTotal());
        assertEquals(0, result.getPages());
    }
}
