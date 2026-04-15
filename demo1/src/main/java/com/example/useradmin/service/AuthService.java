package com.example.useradmin.service;

import com.example.useradmin.dto.LoginDTO;
import com.example.useradmin.dto.RegisterDTO;
import com.example.useradmin.vo.LoginVO;

public interface AuthService {

    LoginVO login(LoginDTO loginDTO);

    void register(RegisterDTO registerDTO);

    LoginVO refreshToken(String refreshToken);

    void logout();
}
