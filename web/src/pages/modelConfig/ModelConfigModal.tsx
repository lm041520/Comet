import { useEffect } from 'react'
import { Form, Input, Modal, Select, Switch } from 'antd'
import type { ModelConfigItem, ModelConfigPayload, Provider } from '@/api/models'
import {
  CAPABILITY_OPTIONS,
  PROVIDER_DEFAULT_BASE_URL,
  PROVIDER_OPTIONS,
  TYPE_OPTIONS,
} from './constants'

interface Props {
  open: boolean
  editing: ModelConfigItem | null
  confirmLoading: boolean
  onCancel: () => void
  onSubmit: (values: ModelConfigPayload) => void
}

export default function ModelConfigModal({
  open,
  editing,
  confirmLoading,
  onCancel,
  onSubmit,
}: Props) {
  const [form] = Form.useForm<ModelConfigPayload>()
  const isEdit = !!editing

  useEffect(() => {
    if (open) {
      if (editing) {
        form.setFieldsValue({
          type: editing.type,
          provider: editing.provider,
          name: editing.name,
          model_name: editing.model_name,
          api_key: '', // 编辑时留空表示不修改
          base_url: editing.base_url,
          capability: editing.capability,
          is_default: editing.is_default,
        })
      } else {
        form.resetFields()
        form.setFieldsValue({
          type: 'chat',
          provider: 'deepseek',
          base_url: PROVIDER_DEFAULT_BASE_URL.deepseek,
          capability: [],
          is_default: false,
        })
      }
    }
  }, [open, editing, form])

  // provider 变化时自动填默认 base_url
  const onProviderChange = (p: Provider) => {
    form.setFieldsValue({ base_url: PROVIDER_DEFAULT_BASE_URL[p] })
  }

  return (
    <Modal
      title={isEdit ? '编辑模型配置' : '新增模型配置'}
      open={open}
      onCancel={onCancel}
      onOk={() => form.submit()}
      confirmLoading={confirmLoading}
      destroyOnClose
      width={520}
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={onSubmit}
        requiredMark={false}
        style={{ marginTop: 12 }}
      >
        <Form.Item name="type" label="模型类型" rules={[{ required: true }]}>
          <Select options={TYPE_OPTIONS} disabled={isEdit} />
        </Form.Item>
        <Form.Item name="provider" label="供应商" rules={[{ required: true }]}>
          <Select
            options={PROVIDER_OPTIONS}
            disabled={isEdit}
            onChange={onProviderChange}
          />
        </Form.Item>
        <Form.Item
          name="name"
          label="配置名称"
          rules={[{ required: true, message: '请输入配置名称' }]}
        >
          <Input placeholder="如：我的 DeepSeek 对话模型" />
        </Form.Item>
        <Form.Item
          name="model_name"
          label="模型名称"
          rules={[{ required: true, message: '请输入模型名称' }]}
        >
          <Input placeholder="如：deepseek-chat / gpt-4o / text-embedding-v3" />
        </Form.Item>
        <Form.Item
          name="api_key"
          label="API Key"
          rules={isEdit ? [] : [{ required: true, message: '请输入 API Key' }]}
          extra={isEdit ? '留空则不修改原 Key' : undefined}
        >
          <Input.Password placeholder={isEdit ? '••••••（留空不改）' : 'sk-...'} />
        </Form.Item>
        <Form.Item
          name="base_url"
          label="Base URL"
          rules={[{ required: true, message: '请输入 Base URL' }]}
        >
          <Input placeholder="https://..." />
        </Form.Item>
        <Form.Item name="capability" label="模型能力">
          <Select
            mode="multiple"
            options={CAPABILITY_OPTIONS}
            placeholder="可选，标记是否支持工具调用 / 图片理解"
          />
        </Form.Item>
        <Form.Item name="is_default" label="设为该类型默认" valuePropName="checked">
          <Switch />
        </Form.Item>
      </Form>
    </Modal>
  )
}
