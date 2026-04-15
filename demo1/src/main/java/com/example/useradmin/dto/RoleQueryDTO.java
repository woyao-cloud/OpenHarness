package com.example.useradmin.dto;

import lombok.Data;

@Data
public class RoleQueryDTO {

    private String keyword;

    private Integer status;

    private Long current = 1L;

    private Long size = 10L;
}
