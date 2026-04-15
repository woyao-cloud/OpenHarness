package com.example.useradmin.service.impl;

import com.example.useradmin.common.exception.BusinessException;
import com.example.useradmin.dto.LoginDTO;
import com.example.useradmin.dto.RegisterDTO;
import com.example.useradmin.entity.User;
import com.example.useradmin.mapper.UserMapper;
import com.example.useradmin.security.JwtTokenProvider;
import com.example.useradmin.service.AuthService;
import com.example.useradmin.vo.LoginVO;
import com.example.useradmin.vo.UserVO;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.BeanUtils;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class AuthServiceImpl implements AuthService {

    private final AuthenticationManager authenticationManager;
    private final JwtTokenProvider jwtTokenProvider;
    private final UserMapper userMapper;
    private final PasswordEncoder passwordEncoder;

    @Override
    public LoginVO login(LoginDTO loginDTO) {
        Authentication authentication = authenticationManager.authenticate(
                new UsernamePasswordAuthenticationToken(
                        loginDTO.getUsername(),
                        loginDTO.getPassword()
                )
        );

        SecurityContextHolder.getContext().setAuthentication(authentication);

        String accessToken = jwtTokenProvider.generateAccessToken(authentication);
        String refreshToken = jwtTokenProvider.generateRefreshToken(authentication);

        User user = userMapper.selectByUsername(loginDTO.getUsername());

        LoginVO loginVO = new LoginVO();
        loginVO.setAccessToken(accessToken);
        loginVO.setRefreshToken(refreshToken);
        loginVO.setExpiresIn(jwtTokenProvider.getExpiration());
        loginVO.setUserInfo(convertToVO(user));

        return loginVO;
    }

    @Override
    public void register(RegisterDTO registerDTO) {
        if (userMapper.selectByUsername(registerDTO.getUsername()) != null) {
            throw new BusinessException("用户名已存在");
        }

        User user = new User();
        user.setUsername(registerDTO.getUsername());
        user.setPassword(passwordEncoder.encode(registerDTO.getPassword()));
        user.setNickname(registerDTO.getNickname());
        user.setEmail(registerDTO.getEmail());
        user.setPhone(registerDTO.getPhone());
        user.setStatus(1);
        user.setRole("USER");

        userMapper.insert(user);
    }

    @Override
    public LoginVO refreshToken(String refreshToken) {
        if (!jwtTokenProvider.validateToken(refreshToken) || !jwtTokenProvider.isRefreshToken(refreshToken)) {
            throw new BusinessException(401, "无效的刷新令牌");
        }

        String username = jwtTokenProvider.getUsernameFromToken(refreshToken);
        String newAccessToken = jwtTokenProvider.generateAccessTokenFromUsername(username);

        User user = userMapper.selectByUsername(username);

        LoginVO loginVO = new LoginVO();
        loginVO.setAccessToken(newAccessToken);
        loginVO.setRefreshToken(refreshToken);
        loginVO.setExpiresIn(jwtTokenProvider.getExpiration());
        loginVO.setUserInfo(convertToVO(user));

        return loginVO;
    }

    @Override
    public void logout() {
        SecurityContextHolder.clearContext();
    }

    private UserVO convertToVO(User user) {
        UserVO vo = new UserVO();
        BeanUtils.copyProperties(user, vo);
        return vo;
    }
}
