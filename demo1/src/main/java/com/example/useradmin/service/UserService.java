package com.example.useradmin.service;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.service.IService;
import com.example.useradmin.dto.PasswordDTO;
import com.example.useradmin.dto.UserCreateDTO;
import com.example.useradmin.dto.UserUpdateDTO;
import com.example.useradmin.entity.User;
import com.example.useradmin.vo.UserVO;

public interface UserService extends IService<User> {

    IPage<UserVO> getUserPage(Long current, Long size, String keyword);

    UserVO getUserById(Long id);

    UserVO createUser(UserCreateDTO dto);

    UserVO updateUser(Long id, UserUpdateDTO dto);

    void deleteUser(Long id);

    void updateUserStatus(Long id, Integer status);

    UserVO getCurrentUser();

    UserVO updateCurrentUser(UserUpdateDTO dto);

    void updatePassword(PasswordDTO dto);
}
