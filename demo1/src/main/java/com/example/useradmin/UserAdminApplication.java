package com.example.useradmin;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
@MapperScan("com.example.useradmin.mapper")
public class UserAdminApplication {
    public static void main(String[] args) {
        SpringApplication.run(UserAdminApplication.class, args);
    }
}
