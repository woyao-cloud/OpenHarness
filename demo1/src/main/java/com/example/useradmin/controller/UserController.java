package com.example.useradmin.controller;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.example.useradmin.common.PageResult;
import com.example.useradmin.common.Result;
import com.example.useradmin.dto.PasswordDTO;
import com.example.useradmin.dto.UserCreateDTO;
import com.example.useradmin.dto.UserUpdateDTO;
import com.example.useradmin.service.UserService;
import com.example.useradmin.vo.UserVO;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@Tag(name = "用户管理", description = "用户CRUD操作接口")
@RestController
@RequestMapping("/api/users")
@RequiredArgsConstructor
public class UserController {

    private final UserService userService;

    @Operation(summary = "分页查询用户列表（管理员）")
    @GetMapping
    @PreAuthorize("hasRole('ADMIN')")
    public Result<PageResult<UserVO>> getUserPage(
            @Parameter(description = "当前页") @RequestParam(defaultValue = "1") Long current,
            @Parameter(description = "每页大小") @RequestParam(defaultValue = "10") Long size,
            @Parameter(description = "搜索关键词") @RequestParam(required = false) String keyword) {
        IPage<UserVO> page = userService.getUserPage(current, size, keyword);
        return Result.success(PageResult.of(page));
    }

    @Operation(summary = "获取用户详情（管理员）")
    @GetMapping("/{id}")
    @PreAuthorize("hasRole('ADMIN')")
    public Result<UserVO> getUserById(@Parameter(description = "用户ID") @PathVariable Long id) {
        return Result.success(userService.getUserById(id));
    }

    @Operation(summary = "创建用户（管理员）")
    @PostMapping
    @PreAuthorize("hasRole('ADMIN')")
    public Result<UserVO> createUser(@Valid @RequestBody UserCreateDTO dto) {
        return Result.success(userService.createUser(dto));
    }

    @Operation(summary = "更新用户（管理员）")
    @PutMapping("/{id}")
    @PreAuthorize("hasRole('ADMIN')")
    public Result<UserVO> updateUser(
            @Parameter(description = "用户ID") @PathVariable Long id,
            @Valid @RequestBody UserUpdateDTO dto) {
        return Result.success(userService.updateUser(id, dto));
    }

    @Operation(summary = "删除用户（管理员）")
    @DeleteMapping("/{id}")
    @PreAuthorize("hasRole('ADMIN')")
    public Result<Void> deleteUser(@Parameter(description = "用户ID") @PathVariable Long id) {
        userService.deleteUser(id);
        return Result.success();
    }

    @Operation(summary = "修改用户状态（管理员）")
    @PutMapping("/{id}/status")
    @PreAuthorize("hasRole('ADMIN')")
    public Result<Void> updateUserStatus(
            @Parameter(description = "用户ID") @PathVariable Long id,
            @RequestBody Map<String, Integer> request) {
        userService.updateUserStatus(id, request.get("status"));
        return Result.success();
    }

    @Operation(summary = "获取当前登录用户信息")
    @GetMapping("/profile")
    public Result<UserVO> getCurrentUser() {
        return Result.success(userService.getCurrentUser());
    }

    @Operation(summary = "更新当前登录用户信息")
    @PutMapping("/profile")
    public Result<UserVO> updateCurrentUser(@Valid @RequestBody UserUpdateDTO dto) {
        return Result.success(userService.updateCurrentUser(dto));
    }

    @Operation(summary = "修改当前登录用户密码")
    @PutMapping("/password")
    public Result<Void> updatePassword(@Valid @RequestBody PasswordDTO dto) {
        userService.updatePassword(dto);
        return Result.success();
    }
}
