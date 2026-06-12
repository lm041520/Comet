import { useEffect, useState } from 'react'
import { Button, Dropdown, Empty, Popconfirm, Spin, Switch, Tag, Tooltip, message } from 'antd'
import {
  DeleteOutlined,
  EditOutlined,
  ExclamationCircleFilled,
  PlusOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { skillApi, type BuiltinSkill, type Skill } from '@/api/skills'
import { useSkillStore } from '@/stores/skillStore'
import SkillEditModal from './skill/SkillEditModal'

export default function SkillPage() {
  const skills = useSkillStore((s) => s.list)
  const loading = useSkillStore((s) => s.loading)
  const refresh = useSkillStore((s) => s.refresh)
  const [builtins, setBuiltins] = useState<BuiltinSkill[]>([])
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<Skill | null>(null)
  const [addingKey, setAddingKey] = useState<string | null>(null)

  useEffect(() => {
    refresh()
    skillApi
      .builtins()
      .then(({ data }) => setBuiltins(data))
      .catch(() => setBuiltins([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const onCreate = () => {
    setEditing(null)
    setEditOpen(true)
  }
  const onEdit = (s: Skill) => {
    setEditing(s)
    setEditOpen(true)
  }
  const onDelete = async (s: Skill) => {
    try {
      await skillApi.remove(s.id)
      message.success('已删除')
      refresh()
    } catch (e) {
      message.error((e as Error).message)
    }
  }
  const onToggleEnabled = async (s: Skill, enabled: boolean) => {
    try {
      await skillApi.update(s.id, { enabled })
      refresh()
    } catch (e) {
      message.error((e as Error).message)
    }
  }
  const onAddBuiltin = async (key: string) => {
    setAddingKey(key)
    try {
      await skillApi.addBuiltin(key)
      message.success('已添加到我的技能')
      refresh()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setAddingKey(null)
    }
  }

  return (
    <div className="fluid-page skill-page">
      <div className="skill-hero">
        <div className="skill-hero-bg" />
        <div className="skill-hero-content">
          <div>
            <div className="skill-hero-title">我的技能</div>
            <div className="skill-hero-sub">
              把「提示词 + 限定工具 + 知识库」打包成任务能力，对话中一键挂载
            </div>
          </div>
          <Dropdown
            disabled={builtins.length === 0}
            menu={{
              items: builtins.map((b) => ({
                key: b.key,
                label: (
                  <span>
                    {b.icon} {b.name}
                  </span>
                ),
                onClick: () => onAddBuiltin(b.key),
              })),
            }}
          >
            <Button icon={<ThunderboltOutlined />} loading={!!addingKey}>
              从模板添加
            </Button>
          </Dropdown>
        </div>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 60 }}>
          <Spin />
        </div>
      ) : (
        <div className="skill-gallery">
          <button className="skill-ghost-card" onClick={onCreate}>
            <PlusOutlined className="skill-ghost-plus" />
            <span>新建技能</span>
          </button>

          {skills.map((s) => (
            <div key={s.id} className="skill-card">
              <div className="skill-card-head">
                <span className="skill-card-icon">{s.icon}</span>
                <div className="skill-card-title">
                  {s.name}
                  {s.is_builtin && (
                    <Tag color="blue" style={{ marginLeft: 6 }}>
                      模板
                    </Tag>
                  )}
                </div>
              </div>
              <div className="skill-card-desc">{s.description || '暂无简介'}</div>
              <div className="skill-card-meta">
                {(s.tool_keys?.length ?? 0) > 0 && (
                  <Tag>限定 {s.tool_keys.length} 个工具</Tag>
                )}
                {s.kb_id && <Tag color="geekblue">绑定知识库</Tag>}
                {(s.config?.quick_prompts?.length ?? 0) > 0 && (
                  <Tag color="green">{s.config!.quick_prompts!.length} 条快捷提问</Tag>
                )}
              </div>
              <div className="skill-card-actions">
                <Tooltip title="开启后在对话框技能选择器中显示">
                  <span className="skill-card-toggle">
                    <Switch
                      size="small"
                      checked={s.enabled}
                      onChange={(v) => onToggleEnabled(s, v)}
                    />
                    <span className="skill-card-toggle-label">对话显示</span>
                  </span>
                </Tooltip>
                <span style={{ flex: 1 }} />
                <Button
                  type="text"
                  size="small"
                  icon={<EditOutlined />}
                  onClick={() => onEdit(s)}
                >
                  编辑
                </Button>
                <Popconfirm
                  title="删除技能"
                  description="删除后不可恢复，确定删除吗？"
                  icon={<ExclamationCircleFilled style={{ color: '#FF5D34' }} />}
                  okButtonProps={{ danger: true }}
                  okText="删除"
                  cancelText="取消"
                  onConfirm={() => onDelete(s)}
                >
                  <Button type="text" size="small" danger icon={<DeleteOutlined />}>
                    删除
                  </Button>
                </Popconfirm>
              </div>
            </div>
          ))}
        </div>
      )}

      {!loading && skills.length === 0 && (
        <Empty
          description="还没有技能，新建一个或从模板添加吧"
          style={{ marginTop: 12 }}
        />
      )}

      <SkillEditModal
        open={editOpen}
        skill={editing}
        onClose={() => setEditOpen(false)}
        onSaved={refresh}
      />
    </div>
  )
}
