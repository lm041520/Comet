import { useEffect, useMemo, useState } from 'react'
import {
  Button,
  Empty,
  Popconfirm,
  Spin,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import {
  ApiOutlined,
  CheckCircleFilled,
  DeleteOutlined,
  EditOutlined,
  GlobalOutlined,
  KeyOutlined,
  PlusOutlined,
  StarFilled,
  ThunderboltOutlined,
} from '@ant-design/icons'
import {
  modelApi,
  type ModelConfigItem,
  type ModelConfigPayload,
  type ModelType,
} from '@/api/models'
import ModelConfigModal from './modelConfig/ModelConfigModal'
import { PROVIDER_OPTIONS, TYPE_LABEL } from './modelConfig/constants'

const PROVIDER_LABEL = Object.fromEntries(
  PROVIDER_OPTIONS.map((p) => [p.value, p.label]),
)

// 每种模型类型一套配色 + 分组标题
const TYPE_META: Record<
  ModelType,
  { color: string; bg: string; gradient: string; desc: string }
> = {
  chat: {
    color: '#155EEF',
    bg: '#EEF4FF',
    gradient: 'linear-gradient(135deg, #155EEF 0%, #4E8CFF 100%)',
    desc: '负责对话问答的大语言模型',
  },
  multimodal: {
    color: '#7A5AF8',
    bg: '#F4F1FE',
    gradient: 'linear-gradient(135deg, #7A5AF8 0%, #B69CFF 100%)',
    desc: '能看图理解的多模态模型',
  },
  embedding: {
    color: '#0E9384',
    bg: '#E6F6F4',
    gradient: 'linear-gradient(135deg, #0E9384 0%, #4FD1C5 100%)',
    desc: '把文本转成向量用于检索',
  },
  rerank: {
    color: '#DD6B20',
    bg: '#FEF3E8',
    gradient: 'linear-gradient(135deg, #DD6B20 0%, #F6AD55 100%)',
    desc: '对检索结果重排，提升相关度',
  },
  websearch: {
    color: '#0BA5EC',
    bg: '#E7F6FE',
    gradient: 'linear-gradient(135deg, #0BA5EC 0%, #5CC9F5 100%)',
    desc: '联网搜索实时信息',
  },
}

const TYPE_ORDER: ModelType[] = [
  'chat',
  'multimodal',
  'embedding',
  'rerank',
  'websearch',
]

const CAP_LABEL: Record<string, string> = {
  function_call: '工具调用',
  vision: '图片理解',
}

// 密钥掩码归一化：统一显示为「固定圆点 + 真实尾部」，避免长短不一撑乱卡片
function normalizeKey(masked: string): string {
  if (!masked) return '-'
  // 取末尾连续的非掩码字符作为可见尾部（后端掩码用 * 号）
  const tail = masked.replace(/\*+/g, '').slice(-4)
  return `${'•'.repeat(12)}${tail}`
}

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

  // 按类型排序展示（统一两列网格，不再按类型分块）
  const sorted = useMemo(
    () =>
      [...list].sort(
        (a, b) => TYPE_ORDER.indexOf(a.type) - TYPE_ORDER.indexOf(b.type),
      ),
    [list],
  )

  const renderCard = (item: ModelConfigItem) => {
    const meta = TYPE_META[item.type]
    const provider = PROVIDER_LABEL[item.provider] ?? item.provider
    return (
      <div key={item.id} className="model-card">
        <div className="model-card-glow" style={{ background: meta.gradient }} />
        <div className="model-card-head">
          <div
            className="model-card-icon"
            style={{ background: meta.gradient }}
          >
            <ApiOutlined />
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="model-card-title">
              <span className="model-card-name" title={item.name}>
                {item.name}
              </span>
              {item.is_default && (
                <Tooltip title="默认配置">
                  <StarFilled style={{ color: '#FAAD14', fontSize: 14 }} />
                </Tooltip>
              )}
            </div>
            <div className="model-card-provider">
              <GlobalOutlined style={{ fontSize: 12 }} /> {provider}
            </div>
          </div>
          <Tag
            style={{
              margin: 0,
              border: 'none',
              color: meta.color,
              background: meta.bg,
              fontWeight: 500,
              borderRadius: 6,
            }}
          >
            {TYPE_LABEL[item.type]}
          </Tag>
        </div>

        <div className="model-card-body">
          <div className="model-card-row">
            <ThunderboltOutlined style={{ color: '#98A2B3' }} />
            <span className="model-card-label">模型</span>
            <span className="model-card-value" title={item.model_name}>
              {item.model_name || '-'}
            </span>
          </div>
          <div className="model-card-row">
            <KeyOutlined style={{ color: '#98A2B3' }} />
            <span className="model-card-label">密钥</span>
            <span className="model-card-value model-card-key" title={item.api_key_masked}>
              {normalizeKey(item.api_key_masked)}
            </span>
          </div>
          {item.capability.length > 0 && (
            <div className="model-card-row">
              <CheckCircleFilled style={{ color: '#52C41A' }} />
              <span className="model-card-label">能力</span>
              <span style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                {item.capability.map((c) => (
                  <Tag
                    key={c}
                    color="green"
                    style={{ margin: 0, borderRadius: 6 }}
                  >
                    {CAP_LABEL[c] ?? c}
                  </Tag>
                ))}
              </span>
            </div>
          )}
        </div>

        <div className="model-card-actions">
          <Button
            size="small"
            type="text"
            loading={testingId === item.id}
            icon={<ApiOutlined />}
            onClick={() => onTest(item.id)}
          >
            测试
          </Button>
          {!item.is_default && (
            <Button
              size="small"
              type="text"
              icon={<StarFilled />}
              onClick={() => onSetDefault(item.id)}
            >
              设默认
            </Button>
          )}
          <Button
            size="small"
            type="text"
            icon={<EditOutlined />}
            onClick={() => openEdit(item)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确定删除该配置？"
            onConfirm={() => onDelete(item.id)}
          >
            <Button size="small" type="text" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </div>
      </div>
    )
  }

  return (
    <div className="fluid-page" style={{ maxWidth: '80rem' }}>
      <div className="model-page-header">
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>
            模型配置
          </Typography.Title>
          <Typography.Text type="secondary">
            管理对话、多模态、向量、重排与联网搜索模型，密钥加密存储
          </Typography.Text>
        </div>
        <Button
          type="primary"
          size="large"
          icon={<PlusOutlined />}
          onClick={openCreate}
        >
          新增配置
        </Button>
      </div>

      <Spin spinning={loading}>
        {sorted.length === 0 && !loading ? (
          <Empty
            style={{ padding: '60px 0' }}
            description="还没有模型配置，点击右上角新增一个"
          />
        ) : (
          <div className="model-card-grid">{sorted.map(renderCard)}</div>
        )}
      </Spin>

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
