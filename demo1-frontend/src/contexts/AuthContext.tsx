import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import { UserVO, LoginVO } from '@/types';
import { authApi } from '@/api';
import { setTokens, clearTokens, getAccessToken } from '@/utils/request';
import { message } from 'antd';

interface AuthContextType {
  user: UserVO | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (values: { username: string; password: string; nickname?: string; email?: string; phone?: string }) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<UserVO | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const isAuthenticated = !!user;

  // 刷新用户信息 - 使用 useCallback 避免重复创建函数
  const refreshUser = useCallback(async () => {
    const { userApi } = await import('@/api');
    const profileResponse = await userApi.getProfile();
    setUser(profileResponse.data.data);
  }, []);

  // 初始化时检查登录状态 - 只在组件挂载时执行一次
  useEffect(() => {
    let isMounted = true;
    const initAuth = async () => {
      const token = getAccessToken();
      if (token) {
        try {
          const { userApi } = await import('@/api');
          const profileResponse = await userApi.getProfile();
          if (isMounted) {
            setUser(profileResponse.data.data);
          }
        } catch {
          clearTokens();
        }
      }
      if (isMounted) {
        setIsLoading(false);
      }
    };
    initAuth();
    return () => {
      isMounted = false;
    };
  }, []);

  // 登录
  const login = async (username: string, password: string) => {
    const response = await authApi.login({ username, password });
    const loginData: LoginVO = response.data.data;
    setTokens(loginData);
    setUser(loginData.userInfo);
    localStorage.setItem('userInfo', JSON.stringify(loginData.userInfo));
    message.success('登录成功');
  };

  // 注册
  const register = async (values: { username: string; password: string; nickname?: string; email?: string; phone?: string }) => {
    await authApi.register(values);
    message.success('注册成功，请登录');
  };

  // 登出
  const logout = async () => {
    try {
      await authApi.logout();
    } finally {
      clearTokens();
      setUser(null);
      message.success('已退出登录');
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated,
        isLoading,
        login,
        register,
        logout,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
