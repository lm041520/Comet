import { useEffect, useState } from 'react'
import { Empty, Modal, Spin, Switch, Tabs, Tooltip, message } from 'antd'
import {
  ExclamationCircleFilled,
  DownOutlined,
  MessageOutlined,
  PlusOutlined,
  QuestionCircleOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { agentConfigApi } from '@/api/agentConfig'
import { personaApi, type Persona } from '@/api/personas'
import {
  personaGroupApi,
  type BuiltinGroup,
  type PersonaGroup,
} from '@/api/personaGroups'
import GroupMemberAvatars from '@/components/GroupMemberAvatars'
import PersonaCard from './agent/PersonaCard'
import PersonaEditModal from './agent/PersonaEditModal'
import PersonaGroupEditModal from './agent/PersonaGroupEditModal'

export default function AgentConfigPage() {
  const navigate = useNavigate()
  const [personas, setPersonas] = useState<Persona[]>([])
  const [groups, setGroups] = useState<PersonaGroup[]>([])
  const [builtins, setBuiltins] = useState<BuiltinGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [showAvatar, setShowAvatar] = useState(false)
  const [activeRecall, setActiveRecall] = useState(true)
  const [crossSession, setCrossSession] = useState(false)
  const [humanMode, setHumanMode] = useState(false)
  const [activatingId, setActivatingId] = useState<string | null>(null)
  const [busyKey, setBusyKey] = useState<string | null>(null)
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<Persona | null>(null)
  const [groupEditOpen, setGroupEditOpen] = useState(false)
  const [editingGroup, setEditingGroup] = useState<PersonaGroup | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const [pResp, cResp] = await Promise.all([
        personaApi.list(),
        agentConfigApi.get(),
      ])
      setPersonas(pResp.data)
      setShowAvatar(cResp.data.show_avatar)
      setActiveRecall(cResp.data.enable_active_recall)
      setCrossSession(cResp.data.enable_cross_session)
      setHumanMode(cResp.data.human_mode)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setLoading(false)
    }
    loadGroups()
  }

  const loadGroups = () => {
    personaGroupApi
      .list()
      .then((r) => setGroups(r.data))
      .catch(() => {})
    personaGroupApi
      .listBuiltins()
      .then((r) => setBuiltins(r.data))
      .catch(() => {})
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const onToggleAvatar = async (v: boolean) => {
    setShowAvatar(v)
    try {
      await agentConfigApi.update({ show_avatar: v })
    } catch (e) {
      setShowAvatar(!v)
      message.error((e as Error).message)
    }
  }

  const onToggleActiveRecall = async (v: boolean) => {
    setActiveRecall(v)
    try {
      await agentConfigApi.update({ enable_active_recall: v })
    } catch (e) {
      setActiveRecall(!v)
      message.error((e as Error).message)
    }
  }

  const onToggleCrossSession = async (v: boolean) => {
    setCrossSession(v)
    try {
      await agentConfigApi.update({ enable_cross_session: v })
    } catch (e) {
      setCrossSession(!v)
      message.error((e as Error).message)
    }
  }

  const onToggleHumanMode = async (v: boolean) => {
    setHumanMode(v)
    try {
      await agentConfigApi.update({ human_mode: v })
    } catch (e) {
      setHumanMode(!v)
      message.error((e as Error).message)
    }
  }

  const onActivate = async (p: Persona) => {
    setActivatingId(p.id)
    try {
      await personaApi.activate(p.id)
      setPersonas((prev) => prev.map((x) => ({ ...x, is_active: x.id === p.id })))
      message.success(`已切换到「${p.name}」`)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setActivatingId(null)
    }
  }

  const onDelete = async (p: Persona) => {
    try {
      await personaApi.remove(p.id)
      message.success('已删除')
      load()
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const onCreate = () => {
    setEditing(null)
    setEditOpen(true)
  }
  const onEdit = (p: Persona) => {
    setEditing(p)
    setEditOpen(true)
  }

  // ── 卡组操作 ──
  const onAddBuiltin = async (b: BuiltinGroup) => {
    setBusyKey(b.key)
    try {
      await personaGroupApi.addBuiltin(b.key)
      message.success(`已添加「${b.name}」`)
      loadGroups()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setBusyKey(null)
    }
  }

  const onOpenGroupChat = async (g: PersonaGroup) => {
    setBusyKey(g.id)
    try {
      await personaGroupApi.openChat(g.id)
      message.success('已开启群聊')
      navigate('/group-chat')
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setBusyKey(null)
    }
  }

  const onDeleteGroup = (g: PersonaGroup) => {
    Modal.confirm({
      title: `删除卡组「${g.name}」？`,
      icon: <ExclamationCircleFilled style={{ color: '#FF5D34' }} />,
      content: '只删除卡组，组内角色仍保留在角色列表中。',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          await personaGroupApi.remove(g.id)
          message.success('已删除')
          loadGroups()
        } catch (e) {
          message.error((e as Error).message)
        }
      },
    })
  }

  const onCreateGroup = () => {
    setEditingGroup(null)
    setGroupEditOpen(true)
  }
  const onEditGroup = (g: PersonaGroup) => {
    setEditingGroup(g)
    setGroupEditOpen(true)
  }

  // 内置场景区折叠态，默认收起（进阶/偶尔用，不喧宾夺主）
  const [builtinOpen, setBuiltinOpen] = useState(false)

  // 已添加的内置卡组 key（按 name 粗略判断，避免重复添加按钮误导）
  const addedNames = new Set(groups.map((g) => g.name))

  const singleTab = (
    <div className="persona-gallery">
      <button className="persona-ghost-card" onClick={onCreate}>
        <PlusOutlined className="persona-ghost-plus" />
        <span>新建角色</span>
      </button>
      {personas.map((p, i) => (
        <PersonaCard
          key={p.id}
          persona={p}
          index={i}
          activating={activatingId === p.id}
          onActivate={onActivate}
          onEdit={onEdit}
          onDelete={onDelete}
        />
      ))}
    </div>
  )

  const groupTab = (
    <div className="pg-tab">
      {/* 内置场景模板（可折叠，默认收起） */}
      {builtins.length > 0 && (
        <div className="scene-section">
          <button
            className="scene-collapse-head"
            onClick={() => setBuiltinOpen((v) => !v)}
            type="button"
          >
            <span className="scene-section-title" style={{ marginBottom: 0 }}>
              🎭 内置场景
              <span className="scene-section-sub">
                一键添加成你的卡组，直接开群聊会诊（共 {builtins.length} 个）
              </span>
            </span>
            <DownOutlined
              className={`scene-collapse-arrow ${builtinOpen ? 'scene-collapse-arrow--open' : ''}`}
            />
          </button>
          {builtinOpen && (
            <div className="scene-grid" style={{ marginTop: 14 }}>
              {builtins.map((b) => (
                <div key={b.key} className="scene-card">
                  <div className="scene-card-icon">{b.icon}</div>
                  <div className="scene-card-body">
                    <div className="scene-card-name">{b.name}</div>
                    <div className="scene-card-desc">{b.description}</div>
                    <div className="scene-card-members">
                      {b.members.map((m) => (
                        <span key={m.name} className="scene-member-tag">
                          {m.name}
                        </span>
                      ))}
                    </div>
                  </div>
                  <button
                    className="scene-card-btn"
                    disabled={busyKey === b.key}
                    onClick={() => onAddBuiltin(b)}
                  >
                    <PlusOutlined />
                    {busyKey === b.key
                      ? '添加中…'
                      : addedNames.has(b.name)
                        ? '再加一个'
                        : '添加到我的卡组'}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 我的卡组 */}
      <div className="scene-section-title" style={{ marginTop: 8 }}>
        🗂 我的卡组
        <span className="scene-section-sub">把几个角色打包成场景，一键开群聊</span>
      </div>
      <div className="pg-grid">
        <button className="persona-ghost-card pg-ghost" onClick={onCreateGroup}>
          <PlusOutlined className="persona-ghost-plus" />
          <span>新建卡组</span>
        </button>
        {groups.map((g) => (
          <div key={g.id} className="pg-card">
            <div className="pg-card-head">
              <div className="pg-card-name">
                {g.icon} {g.name}
              </div>
              <div className="pg-card-count">{g.members.length} 位成员</div>
            </div>
            <GroupMemberAvatars members={g.members} size={40} />
            <div className="pg-card-desc">
              {g.description || (
                <span style={{ color: '#cbd2dd' }}>这个卡组还没有描述</span>
              )}
            </div>
            <div className="pg-card-members">
              {g.members.map((m) => (
                <span key={m.id} className="scene-member-tag">
                  {m.name}
                </span>
              ))}
            </div>
            <div className="pg-card-actions">
              <button
                className="scene-card-btn"
                disabled={busyKey === g.id}
                onClick={() => onOpenGroupChat(g)}
              >
                <MessageOutlined />
                {busyKey === g.id ? '开启中…' : '开始群聊'}
              </button>
              <Tooltip title="编辑">
                <button className="pg-icon-action" onClick={() => onEditGroup(g)}>
                  编辑
                </button>
              </Tooltip>
              <Tooltip title="删除">
                <button
                  className="pg-icon-action pg-icon-action--danger"
                  onClick={() => onDeleteGroup(g)}
                >
                  删除
                </button>
              </Tooltip>
            </div>
          </div>
        ))}
      </div>
      {groups.length === 0 && builtins.length === 0 && (
        <Empty description="还没有卡组" />
      )}
    </div>
  )

  return (
    <div className="fluid-page persona-page">
      <div className="persona-hero">
        <div className="persona-hero-bg" />
        <div className="persona-hero-content">
          <div>
            <div className="persona-hero-title">我的角色</div>
            <div className="persona-hero-sub">
              单个角色化身你想聊的人，卡组把多个角色打包成一键群聊的场景
            </div>
          </div>
          <div className="persona-hero-switches">
          <div className="persona-hero-switch">
            <span>
              显示对话头像
              <Tooltip title="开启后，对话界面会显示当前角色头像与你的头像；关闭则两边都不显示">
                <QuestionCircleOutlined style={{ marginLeft: 6, opacity: 0.7 }} />
              </Tooltip>
            </span>
            <Switch checked={showAvatar} onChange={onToggleAvatar} />
          </div>
          <div className="persona-hero-switch">
            <span>
              主动记忆
              <Tooltip title="开启后，每轮提问会自动检索与话题相关的记忆与「AI 眼中的你」，让回答更懂你；关闭则不注入">
                <QuestionCircleOutlined style={{ marginLeft: 6, opacity: 0.7 }} />
              </Tooltip>
            </span>
            <Switch checked={activeRecall} onChange={onToggleActiveRecall} />
          </div>
          <div className="persona-hero-switch">
            <span>
              跨会话上下文
              <Tooltip title="开启后，提问时会参考你最近其他会话聊过的内容，跨会话也能接着聊；默认关闭，保持各会话独立">
                <QuestionCircleOutlined style={{ marginLeft: 6, opacity: 0.7 }} />
              </Tooltip>
            </span>
            <Switch checked={crossSession} onChange={onToggleCrossSession} />
          </div>
          <div className="persona-hero-switch">
            <span>
              真人对话模式
              <Tooltip title="开启后所有对话/群聊都像真人微信聊天：口语、简短、会分多条气泡连发；关闭恢复助手风格（结构化、可长篇）">
                <QuestionCircleOutlined style={{ marginLeft: 6, opacity: 0.7 }} />
              </Tooltip>
            </span>
            <Switch checked={humanMode} onChange={onToggleHumanMode} />
          </div>
          </div>
        </div>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 60 }}>
          <Spin />
        </div>
      ) : (
        <Tabs
          items={[
            { key: 'single', label: '单个角色', children: singleTab },
            {
              key: 'group',
              label: (
                <span>
                  <TeamOutlined /> 角色卡组
                </span>
              ),
              children: groupTab,
            },
          ]}
        />
      )}

      <PersonaEditModal
        open={editOpen}
        persona={editing}
        onClose={() => setEditOpen(false)}
        onSaved={load}
      />
      <PersonaGroupEditModal
        open={groupEditOpen}
        group={editingGroup}
        onClose={() => setGroupEditOpen(false)}
        onSaved={loadGroups}
      />
    </div>
  )
}
