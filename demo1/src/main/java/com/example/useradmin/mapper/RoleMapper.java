package com.example.useradmin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.example.useradmin.entity.Role;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface RoleMapper extends BaseMapper<Role> {

    @Select("SELECT r.* FROM sys_role r " +
            "INNER JOIN sys_user_role ur ON r.id = ur.role_id " +
            "WHERE ur.user_id = #{userId} AND r.status = 1 AND r.deleted = 0")
    List<Role> selectRolesByUserId(Long userId);

    @Select("SELECT * FROM sys_role WHERE status = 1 AND deleted = 0 ORDER BY role_code")
    List<Role> selectAllActiveRoles();
}
