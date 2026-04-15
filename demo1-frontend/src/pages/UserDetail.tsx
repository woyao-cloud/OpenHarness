import React, { useEffect, useState } from 'react';
import { Form, Input, Button, Card, message, Select, Radio } from 'antd';
import { useParams, useNavigate } from 'react-router-dom';
import { userApi } from '@/api';
import { UserVO } from '@/types';

const { Option } = Select;

const UserDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const isEdit = id !== 'new';

  useEffect(() => {
    if (isEdit && id) {
      fetchUser(parseInt(id));
    }
  }, [id]);

  const fetchUser = async (userId: number) => {
    setLoading(true);
    try {
      const response = await userApi.getById(userId);
      const user = response.data.data;
      form.setFieldsValue(user);
    } finally {
      setLoading(false);
    }
  };

  const onFinish = async (values: Partial<UserVO>) => {
    setSaving(true);
    try {
      if (isEdit && id) {
        await userApi.update(parseInt(id), values);
        message.success('更新成功');
      } else {
        await userApi.create(values);
        message.success('创建成功');
      }
      navigate('/users');
    } catch {
      message.error('操作失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title={isEdit ? '编辑用户' : '新增用户'} loading={loading}>
      <Form
        form={form}
        name="userDetail"
        onFinish={onFinish}
        autoComplete="off"
        layout="vertical"
        style={{ maxWidth: 600 }}
      >
        <Form.Item
          label="用户名"
          name="username"
          rules={[{ required: true, message: '请输入用户名' }]}
        >
          <Input placeholder="请输入用户名" disabled={isEdit} />
        </Form.Item>

        {!isEdit && (
          <Form.Item
            label="密码"
            name="password"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password placeholder="请输入密码" />
          </Form.Item>
        )}

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

        <Form.Item
          label="角色"
          name="role"
          rules={[{ required: true, message: '请选择角色' }]}
        >
          <Select placeholder="请选择角色">
            <Option value="ADMIN">管理员</Option>
            <Option value="USER">普通用户</Option>
          </Select>
        </Form.Item>

        <Form.Item
          label="状态"
          name="status"
          rules={[{ required: true, message: '请选择状态' }]}
        >
          <Radio.Group>
            <Radio value="ACTIVE">启用</Radio>
            <Radio value="INACTIVE">禁用</Radio>
          </Radio.Group>
        </Form.Item>

        <Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" loading={saving}>
              保存
            </Button>
            <Button onClick={() => navigate('/users')}>
              返回
            </Button>
          </Space>
        </Form.Item>
      </Form>
    </Card>
  );
};

export default UserDetail;
