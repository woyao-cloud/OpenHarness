package com.example.useradmin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.example.useradmin.entity.UserRole;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.util.List;

@Mapper
public interface UserRoleMapper extends BaseMapper<UserRole> {

    @Delete("DELETE FROM sys_user_role WHERE user_id = #{userId}")
    void deleteByUserId(Long userId);

    void batchInsert(@Param("userId") Long userId, @Param("roleIds") List<Long> roleIds);
}
