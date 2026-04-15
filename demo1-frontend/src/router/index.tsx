import { createBrowserRouter, Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import MainLayout from '@/components/layout/MainLayout';
import Login from '@/pages/Login';
import Register from '@/pages/Register';
import UserList from '@/pages/UserList';
import UserDetail from '@/pages/UserDetail';
import RoleList from '@/pages/RoleList';
import RoleDetail from '@/pages/RoleDetail';
import Profile from '@/pages/Profile';
import React from 'react';

// 路由守卫组件 - 仅检查登录状态
const ProtectedRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return <div>加载中...</div>;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
};

// 管理员路由守卫
const AdminRoute: React.FC = () => {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return <div>加载中...</div>;
  }

  const isAdmin = user?.roles?.some(r => r.roleCode === 'ADMIN');
  if (!isAdmin) {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
};

// 公开路由
const PublicRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return <div>加载中...</div>;
  }

  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
};

export const router = createBrowserRouter([
  {
    path: '/login',
    element: (
      <PublicRoute>
        <Login />
      </PublicRoute>
    ),
  },
  {
    path: '/register',
    element: (
      <PublicRoute>
        <Register />
      </PublicRoute>
    ),
  },
  {
    path: '/',
    element: (
      <ProtectedRoute>
        <MainLayout />
      </ProtectedRoute>
    ),
    children: [
      {
        index: true,
        element: <Navigate to="/users" replace />,
      },
      {
        path: 'profile',
        element: <Profile />,
      },
      // 管理员专属路由
      {
        path: 'users',
        element: <AdminRoute />,
        children: [
          { index: true, element: <UserList /> },
          { path: ':id', element: <UserDetail /> },
        ],
      },
      {
        path: 'roles',
        element: <AdminRoute />,
        children: [
          { index: true, element: <RoleList /> },
          { path: ':id', element: <RoleDetail /> },
        ],
      },
    ],
  },
]);
