import axios, { AxiosError, AxiosInstance, AxiosRequestConfig, AxiosResponse } from 'axios';
import { ApiResult, LoginVO } from '@/types';
import { message } from 'antd';

// 创建 axios 实例
const request: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 请求队列（用于存储刷新 token 期间的请求）
let isRefreshing = false;
let refreshSubscribers: ((token: string) => void)[] = [];

// 添加请求到队列
const addSubscriber = (callback: (token: string) => void) => {
  refreshSubscribers.push(callback);
};

// 通知所有订阅者
const notifySubscribers = (token: string) => {
  refreshSubscribers.forEach((callback) => callback(token));
  refreshSubscribers = [];
};

// 获取 token
const getAccessToken = (): string | null => {
  return localStorage.getItem('accessToken');
};

// 获取 refresh token
const getRefreshToken = (): string | null => {
  return localStorage.getItem('refreshToken');
};

// 设置 token
const setTokens = (loginVO: LoginVO) => {
  localStorage.setItem('accessToken', loginVO.accessToken);
  localStorage.setItem('refreshToken', loginVO.refreshToken);
};

// 清除 token
const clearTokens = () => {
  localStorage.removeItem('accessToken');
  localStorage.removeItem('refreshToken');
  localStorage.removeItem('userInfo');
};

// 刷新 token
const refreshToken = async (): Promise<string | null> => {
  try {
    const refreshTokenValue = getRefreshToken();
    if (!refreshTokenValue) {
      throw new Error('No refresh token');
    }
    
    const response = await axios.post<ApiResult<LoginVO>>('/api/auth/refresh', {
      refreshToken: refreshTokenValue,
    });
    
    if (response.data.code === 200) {
      setTokens(response.data.data);
      return response.data.data.accessToken;
    }
    throw new Error('Refresh token failed');
  } catch (error) {
    clearTokens();
    window.location.href = '/login';
    return null;
  }
};

// 请求拦截器
request.interceptors.request.use(
  (config: AxiosRequestConfig) => {
    const token = getAccessToken();
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error: AxiosError) => {
    return Promise.reject(error);
  }
);

// 响应拦截器
request.interceptors.response.use(
  (response: AxiosResponse<ApiResult<any>>) => {
    const { data } = response;
    
    // 业务错误处理
    if (data.code !== 200) {
      message.error(data.message || '请求失败');
      return Promise.reject(new Error(data.message));
    }
    
    return response;
  },
  async (error: AxiosError<ApiResult<any>>) => {
    const { response, config } = error;
    
    if (response?.status === 401) {
      // Token 过期，尝试刷新
      if (!isRefreshing) {
        isRefreshing = true;
        const newToken = await refreshToken();
        isRefreshing = false;
        
        if (newToken) {
          notifySubscribers(newToken);
          if (config) {
            config.headers = config.headers || {};
            config.headers.Authorization = `Bearer ${newToken}`;
            return request(config);
          }
        }
      } else {
        // 等待 token 刷新完成
        return new Promise((resolve) => {
          addSubscriber((token: string) => {
            if (config) {
              config.headers = config.headers || {};
              config.headers.Authorization = `Bearer ${token}`;
              resolve(request(config));
            }
          });
        });
      }
    }
    
    // 其他错误
    const errorMessage = response?.data?.message || error.message || '网络错误';
    message.error(errorMessage);
    return Promise.reject(error);
  }
);

export { setTokens, clearTokens, getAccessToken };
export default request;
