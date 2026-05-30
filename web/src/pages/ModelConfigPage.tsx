import { useEffect, useState } from 'react'
import {
  Button,
  Card,
  Empty,
  Popconfirm,
  Space,
  Table,
  Tag,
  message,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import {
  modelApi,
  type ModelConfigItem,
  type ModelConfigPayload,
} from '@/api/models'
import ModelConfigModal from './modelConfig/ModelConfigModal'
import { PROVIDER_OPTIONS, TYPE_LABEL } from './modelConfig/constants'

const PROVIDER_LABEL = Object.fromEntries(
  PROVIDER_OPTIONS.map((p) => [p.value, p.label]),
)

export default function ModelConfigPage() {
  const [list, setList] = useState<ModelConfigItem[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<ModelConfigItem | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [testingId, setTestingId] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await modelApi.list()
      setList(data)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const openCreate = () => {
    setEditing(null)
    setModalOpen(true)
  }

  const openEdit = (item: ModelConfigItem) => {
    setEditing(item)
    setModalOpen(true)
  }

  const onSubmit = async (values: ModelConfigPayload) => {
    setSubmitting(true)
    try {
      if (editing) {
        const payload = { ...values }
        if (!payload.api_key) delete (payload as Partial<ModelConfigPayload>).api_key
        await modelApi.update(editing.id, payload)
        message.success('更新成功')
      } else {
        await modelApi.create(values)
        message.success('创建成功')
      }
      setModalOpen(false)
      load()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  const onDelete = async (id: string) => {
    try {
      await modelApi.remove(id)
      message.success('删除成功')
      load()
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const onTest = async (id: string) => {
    setTestingId(id)
    try {
      const { data } = await modelApi.test(id)
      if (data.success) message.success(data.message)
      else message.error(data.message)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setTestingId(null)
    }
  }

  const onSetDefault = async (id: string) => {
    try {
      await modelApi.setDefault(id)
      message.success('已设为默认')
      load()
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const columns: ColumnsType<ModelConfigItem> = [
    {
      title: '配置名称',
      dataIndex: 'name',
      render: (name, r) => (
        <Space>
          {name}
          {r.is_default && <Tag color="blue">默认</Tag>}
        </Space>
      ),
    },
    {
      title: '类型',
      dataIndex: 'type',
      render: (t) => <Tag>{TYPE_LABEL[t as keyof typeof TYPE_LABEL]}</Tag>,
    },
    {
      title: '供应商',
      dataIndex: 'provider',
      render: (p) => PROVIDER_LABEL[p] ?? p,
    },
    { title: '模型', dataIndex: 'model_name' },
    { title: 'API Key', dataIndex: 'api_key_masked' },
    {
      title: '能力',
      dataIndex: 'capability',
      render: (caps: string[]) =>
        caps.length ? caps.map((c) => <Tag key={c}>{c}</Tag>) : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 280,
      render: (_, r) => (
        <Space size="small">
          <Button
            size="small"
            loading={testingId === r.id}
            onClick={() => onTest(r.id)}
          >
            测试连接
          </Button>
          {!r.is_default && (
            <Button size="small" onClick={() => onSetDefault(r.id)}>
              设默认
            </Button>
          )}
          <Button size="small" type="link" onClick={() => openEdit(r)}>
            编辑
          </Button>
          <Popconfirm title="确定删除该配置？" onConfirm={() => onDelete(r.id)}>
            <Button size="small" type="link" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      <Card
        title="模型配置"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新增配置
          </Button>
        }
      >
        <Table
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={list}
          pagination={false}
          locale={{
            emptyText: (
              <Empty description="还没有模型配置，点击右上角新增一个" />
            ),
          }}
        />
      </Card>
      <ModelConfigModal
        open={modalOpen}
        editing={editing}
        confirmLoading={submitting}
        onCancel={() => setModalOpen(false)}
        onSubmit={onSubmit}
      />
    </div>
  )
}
