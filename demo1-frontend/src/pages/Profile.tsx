import React, { useEffect, useState } from 'react';
import { Form, Input, Button, Card, message, Avatar } from 'antd';
import { UserOutlined } from '@ant-design/icons';
import { useAuth } from '@/contexts/AuthContext';
import { userApi } from '@/api';
import { UserVO } from '@/types';

const Profile: React.FC = () => {
  const { user, refreshUser } = useAuth();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (user) {
      form.setFieldsValue(user);
    }
  }, [user]);

  const onFinish = async (values: Partial<UserVO>) => {
    setLoading(true);
    try {
      if (user?.id) {
        await userApi.updateProfile(values);
        message.success('更新成功');
        await refreshUser();
      }
    } catch {
      message.error('更新失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card title="个人资料">
      <div style={{ textAlign: 'center', marginBottom: 24 }}>
        <Avatar size={80} icon={<UserOutlined />} />
        <h3 style={{ marginTop: 16 }}>{user?.nickname || user?.username}</h3>
        <p style={{ color: '#999' }}>{user?.role === 'ADMIN' ? '管理员' : '普通用户'}</p>
      </div>

      <Form
        form={form}
        name="profile"
        onFinish={onFinish}
        autoComplete="off"
        layout="vertical"
        style={{ maxWidth: 600, margin: '0 auto' }}
      >
        <Form.Item
          label="用户名"
          name="username"
        >
          <Input disabled />
        </Form.Item>

        <Form.Item
          label="昵称"
          name="nickname"
        >
          <Input placeholder="请输入昵称" />
        </Form.Item>

        <Form.Item
          label="邮箱"
          name="email"
          rules={[{ type: 'email', message: '请输入有效的邮箱地址' }]}
        >
          <Input placeholder="请输入邮箱" />
        </Form.Item>

        <Form.Item
          label="手机号"
          name="phone"
        >
          <Input placeholder="请输入手机号" />
        </Form.Item>

        <Form.Item>
          <Button type="primary" htmlType="submit" loading={loading} block>
            保存修改
          </Button>
        </Form.Item>
      </Form>
    </Card>
  );
};

export default Profile;
