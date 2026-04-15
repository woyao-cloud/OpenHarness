package com.example.useradmin.config;

import com.baomidou.mybatisplus.core.handlers.MetaObjectHandler;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class MyBatisPlusConfigTest {

    private final MyBatisPlusConfig config = new MyBatisPlusConfig();

    @Test
    @DisplayName("创建MybatisPlusInterceptor - 成功")
    void mybatisPlusInterceptor_Success() {
        MybatisPlusInterceptor interceptor = config.mybatisPlusInterceptor();
        
        assertNotNull(interceptor);
    }

    @Test
    @DisplayName("创建MetaObjectHandler - 成功")
    void metaObjectHandler_Success() {
        MetaObjectHandler handler = config.metaObjectHandler();
        
        assertNotNull(handler);
    }

    @Test
    @DisplayName("MetaObjectHandler - 插入填充方法存在")
    void metaObjectHandler_HasInsertFill() {
        MetaObjectHandler handler = config.metaObjectHandler();
        
        assertTrue(handler.openInsertFill());
    }

    @Test
    @DisplayName("MetaObjectHandler - 更新填充方法存在")
    void metaObjectHandler_HasUpdateFill() {
        MetaObjectHandler handler = config.metaObjectHandler();
        
        assertTrue(handler.openUpdateFill());
    }
}
