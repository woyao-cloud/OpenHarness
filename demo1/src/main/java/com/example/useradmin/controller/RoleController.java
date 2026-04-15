package com.example.useradmin.controller;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.example.useradmin.common.PageResult;
import com.example.useradmin.common.Result;
import com.example.useradmin.dto.RoleCreateDTO;
import com.example.useradmin.dto.RoleQueryDTO;
import com.example.useradmin.dto.RoleUpdateDTO;
import com.example.useradmin.service.RoleService;
import com.example.useradmin.vo.RoleVO;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@Tag(name = "角色管理", description = "角色CRUD操作接口")
@RestController
@RequestMapping("/api/roles")
@RequiredArgsConstructor
public class RoleController {

    private final RoleService roleService;

    @Operation(summary = "分页查询角色列表")
    @GetMapping
    @PreAuthorize("hasRole('ADMIN')")
    public Result<PageResult<RoleVO>> getRolePage(RoleQueryDTO queryDTO) {
        IPage<RoleVO> page = roleService.getRolePage(queryDTO);
        return Result.success(PageResult.of(page));
    }

    @Operation(summary = "获取角色详情")
    @GetMapping("/{id}")
    @PreAuthorize("hasRole('ADMIN')")
    public Result<RoleVO> getRoleById(@Parameter(description = "角色ID") @PathVariable Long id) {
        return Result.success(roleService.getRoleById(id));
    }

    @Operation(summary = "创建角色")
    @PostMapping
    @PreAuthorize("hasRole('ADMIN')")
    public Result<RoleVO> createRole(@Valid @RequestBody RoleCreateDTO dto) {
        return Result.success(roleService.createRole(dto));
    }

    @Operation(summary = "更新角色")
    @PutMapping("/{id}")
    @PreAuthorize("hasRole('ADMIN')")
    public Result<RoleVO> updateRole(
            @Parameter(description = "角色ID") @PathVariable Long id,
            @Valid @RequestBody RoleUpdateDTO dto) {
        return Result.success(roleService.updateRole(id, dto));
    }

    @Operation(summary = "删除角色")
    @DeleteMapping("/{id}")
    @PreAuthorize("hasRole('ADMIN')")
    public Result<Void> deleteRole(@Parameter(description = "角色ID") @PathVariable Long id) {
        roleService.deleteRole(id);
        return Result.success();
    }

    @Operation(summary = "修改角色状态")
    @PutMapping("/{id}/status")
    @PreAuthorize("hasRole('ADMIN')")
    public Result<Void> updateRoleStatus(
            @Parameter(description = "角色ID") @PathVariable Long id,
            @RequestBody Map<String, Integer> request) {
        roleService.updateRoleStatus(id, request.get("status"));
        return Result.success();
    }

    @Operation(summary = "获取所有有效角色列表（用于下拉选择）")
    @GetMapping("/all")
    @PreAuthorize("hasRole('ADMIN')")
    public Result<List<RoleVO>> getAllActiveRoles() {
        return Result.success(roleService.getAllActiveRoles());
    }
}
