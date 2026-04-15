package com.example.useradmin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.example.useradmin.entity.User;
import com.example.useradmin.vo.RoleVO;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface UserMapper extends BaseMapper<User> {

    @Select("SELECT * FROM sys_user WHERE username = #{username} AND deleted = 0")
    User selectByUsername(@Param("username") String username);

    @Select("SELECT r.id, r.role_code as roleCode, r.role_name as roleName, r.description, r.status, r.create_time as createTime, r.update_time as updateTime " +
            "FROM sys_role r " +
            "INNER JOIN sys_user_role ur ON r.id = ur.role_id " +
            "WHERE ur.user_id = #{userId} AND r.deleted = 0")
    List<RoleVO> selectRolesByUserId(@Param("userId") Long userId);
}
