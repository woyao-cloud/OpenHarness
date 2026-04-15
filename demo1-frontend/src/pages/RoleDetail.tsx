import React, { useEffect, useState } from 'react';
import { Form, Input, Button, Card, message, Radio, Space } from 'antd';
import { useParams, useNavigate } from 'react-router-dom';
import { roleApi } from '@/api';
import { RoleVO } from '@/types';

const RoleDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const isEdit = id !== 'new';

  useEffect(() => {
    if (isEdit && id) {
      fetchRole(parseInt(id));
    }
  }, [id]);

  const fetchRole = async (roleId: number) => {
    setLoading(true);
    try {
      const response = await roleApi.getById(roleId);
      const role = response.data.data;
      form.setFieldsValue(role);
    } finally {
      setLoading(false);
    }
  };

  const onFinish = async (values: Partial<RoleVO>) => {
    setSaving(true);
    try {
      if (isEdit && id) {
        await roleApi.update(parseInt(id), values);
        message.success('更新成功');
      } else {
        await roleApi.create(values);
        message.success('创建成功');
      }
      navigate('/roles');
    } catch {
      message.error('操作失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title={isEdit ? '编辑角色' : '新增角色'} loading={loading}>
      <Form
        form={form}
        name="roleDetail"
        onFinish={onFinish}
        autoComplete="off"
        layout="vertical"
        style={{ maxWidth: 600 }}
      >
        <Form.Item
          label="角色编码"
          name="roleCode"
          rules={[{ required: true, message: '请输入角色编码' }]}
        >
          <Input placeholder="请输入角色编码，如：ADMIN" disabled={isEdit} />
        </Form.Item>

        <Form.Item
          label="角色名称"
          name="roleName"
          rules={[{ required: true, message: '请输入角色名称' }]}
        >
          <Input placeholder="请输入角色名称，如：管理员" />
        </Form.Item>

        <Form.Item
          label="描述"
          name="description"
        >
          <Input.TextArea rows={3} placeholder="请输入角色描述" />
        </Form.Item>

        <Form.Item
          label="状态"
          name="status"
          initialValue={1}
          rules={[{ required: true, message: '请选择状态' }]}
        >
          <Radio.Group>
            <Radio value={1}>启用</Radio>
            <Radio value={0}>禁用</Radio>
          </Radio.Group>
        </Form.Item>

        <Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" loading={saving}>
              保存
            </Button>
            <Button onClick={() => navigate('/roles')}>
              返回
            </Button>
          </Space>
        </Form.Item>
      </Form>
    </Card>
  );
};

export default RoleDetail;
