import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Avatar,
  Button,
  Checkbox,
  Drawer,
  Empty,
  Input,
  Modal,
  Spin,
  Switch,
  Tag,
  Tooltip,
  message as antdMessage,
} from 'antd'
import type { InputRef } from 'antd'
import {
  DeleteOutlined,
  MenuOutlined,
  PlusOutlined,
  SendOutlined,
  ShareAltOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons'
import {
  chatApi,
  groupApi,
  streamGroupChat,
  type Conversation,
  type GroupMember,
} from '@/api/chat'
import { personaApi, type Persona } from '@/api/personas'
import MarkdownMessage from '@/components/MarkdownMessage'
import { AuthenticatedImage } from '@/components/AuthenticatedImage'
import { useAuthStore } from '@/stores/authStore'
import { resolveToolMeta } from '@/pages/chat/types'
import ShareModal from '@/pages/chat/ShareModal'

// 群聊页内的消息模型（含流式态 + 发送者 + 工具调用标记）
interface GroupToolRun {
  tool: string
  query?: string
  status?: string
}
interface GroupUiMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  senderPersonaId?: string | null
  senderName?: string | null
  toolRuns?: GroupToolRun[]
  streaming?: boolean
}

function useIsMobile() {
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== 'undefined' && window.innerWidth <= 768,
  )
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 768px)')
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])
  return isMobile
}

// 成员头像配色池（无头像时按名字稳定取色，避免全是同一种蓝）
const AVATAR_COLORS = [
  '#155EEF',
  '#7C3AED',
  '#0E9F6E',
  '#F05252',
  '#FF8A4C',
  '#0694A2',
]
function colorFor(name: string): string {
  let h = 0
  for (let i = 0; i < name.length; i += 1) h = (h * 31 + name.charCodeAt(i)) % 997
  return AVATAR_COLORS[h % AVATAR_COLORS.length]
}

// 头像：本地存储头像（/api/files/）需带 token 加载，用 AuthenticatedImage 作为
// Avatar 的 src；无头像则显示名字首字 + 稳定配色底。
function PersonaAvatar({
  name,
  avatarUrl,
  size = 38,
  icon,
}: {
  name: string
  avatarUrl?: string | null
  size?: number
  icon?: React.ReactNode
}) {
  return (
    <Avatar
      size={size}
      src={
        avatarUrl ? (
          <AuthenticatedImage
            src={avatarUrl}
            alt={name}
            style={{ width: '100%', height: '100%', objectFit: 'cover' }}
          />
        ) : undefined
      }
      icon={!avatarUrl && icon ? icon : undefined}
      style={{
        flexShrink: 0,
        background: avatarUrl ? undefined : colorFor(name),
        fontWeight: 600,
      }}
    >
      {!icon && name.slice(0, 1)}
    </Avatar>
  )
}

export default function GroupChatPage() {
  const isMobile = useIsMobile()
  const user = useAuthStore((s) => s.user)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<GroupUiMessage[]>([])
  const [members, setMembers] = useState<GroupMember[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [loadingMsgs, setLoadingMsgs] = useState(false)
  const [listOpen, setListOpen] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [shareOpen, setShareOpen] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<InputRef>(null)

  // @ 提及下拉：是否显示 + 过滤关键字 + 高亮项
  const [mentionOpen, setMentionOpen] = useState(false)
  const [mentionKeyword, setMentionKeyword] = useState('')
  const [mentionIndex, setMentionIndex] = useState(0)

  const memberMap = useMemo(
    () => new Map(members.map((m) => [m.id, m])),
    [members],
  )

  const mentionCandidates = useMemo(() => {
    const kw = mentionKeyword.toLowerCase()
    return members.filter((m) => !kw || m.name.toLowerCase().includes(kw))
  }, [members, mentionKeyword])

  const loadConversations = async () => {
    const all = await chatApi.listConversations()
    const groups = (all.data as (Conversation & { is_group?: boolean })[]).filter(
      (c) => c.is_group,
    )
    setConversations(groups)
    return groups
  }

  useEffect(() => {
    loadConversations()
  }, [])

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

  const openConversation = async (id: string) => {
    setActiveId(id)
    setListOpen(false)
    setLoadingMsgs(true)
    try {
      const [msgsResp, membersResp] = await Promise.all([
        chatApi.listMessages(id),
        groupApi.listMembers(id),
      ])
      setMembers(membersResp.data)
      setMessages(
        msgsResp.data.map((m) => ({
          id: m.id,
          role: m.role as 'user' | 'assistant',
          content: m.content,
          senderPersonaId: (m as { sender_persona_id?: string }).sender_persona_id,
          senderName: (m as { sender_name?: string }).sender_name,
          toolRuns: (m.meta_data?.tool_calls as GroupToolRun[] | undefined)?.map(
            (t) => ({ tool: t.tool, query: t.query, status: 'success' }),
          ),
        })),
      )
    } finally {
      setLoadingMsgs(false)
    }
  }

  // ── @ 提及处理 ──
  const handleInputChange = (val: string) => {
    setInput(val)
    // 取光标前文本里最后一个 @ 之后的内容判断是否在提及态
    const atIdx = val.lastIndexOf('@')
    if (atIdx === -1) {
      setMentionOpen(false)
      return
    }
    const after = val.slice(atIdx + 1)
    // @ 后若已含空格则视为结束
    if (/\s/.test(after)) {
      setMentionOpen(false)
      return
    }
    setMentionKeyword(after)
    setMentionIndex(0)
    setMentionOpen(true)
  }

  const applyMention = (name: string) => {
    const atIdx = input.lastIndexOf('@')
    const next = (atIdx === -1 ? input : input.slice(0, atIdx)) + `@${name} `
    setInput(next)
    setMentionOpen(false)
    setTimeout(() => inputRef.current?.focus(), 0)
  }

  const handleSend = async () => {
    const text = input.trim()
    if (!text || !activeId || sending) return
    setInput('')
    setMentionOpen(false)
    setSending(true)
    setMessages((prev) => [
      ...prev,
      { id: `u-${Date.now()}`, role: 'user', content: text },
    ])

    let currentId: string | null = null
    try {
      await streamGroupChat(activeId, text, {
        onSpeakerStart: (d) => {
          currentId = `s-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
          setMessages((prev) => [
            ...prev,
            {
              id: currentId as string,
              role: 'assistant',
              content: '',
              senderPersonaId: d.persona_id,
              senderName: d.name,
              streaming: true,
            },
          ])
        },
        onToken: (t) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === currentId ? { ...m, content: m.content + t } : m,
            ),
          )
        },
        onToolStart: (d) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === currentId
                ? {
                    ...m,
                    toolRuns: [
                      ...(m.toolRuns || []),
                      { tool: d.tool, query: d.query, status: 'running' },
                    ],
                  }
                : m,
            ),
          )
        },
        onToolResult: (d) => {
          setMessages((prev) =>
            prev.map((m) => {
              if (m.id !== currentId) return m
              const runs = [...(m.toolRuns || [])]
              // 回填最近一条同名 running
              for (let i = runs.length - 1; i >= 0; i -= 1) {
                if (runs[i].tool === d.tool && runs[i].status === 'running') {
                  runs[i] = { ...runs[i], status: d.status || 'success' }
                  break
                }
              }
              return { ...m, toolRuns: runs }
            }),
          )
        },
        onSpeakerEnd: (d) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === currentId
                ? { ...m, id: d.message_id, streaming: false }
                : m,
            ),
          )
          currentId = null
        },
        onError: (msg) => {
          antdMessage.error(msg)
        },
      })
      loadConversations()
    } catch {
      antdMessage.error('群聊发送失败')
    } finally {
      setSending(false)
    }
  }

  const handleDelete = (id: string) => {
    Modal.confirm({
      title: '删除该群聊？',
      content: '群聊记录将一并删除，无法恢复。',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        await chatApi.deleteConversation(id)
        if (activeId === id) {
          setActiveId(null)
          setMessages([])
          setMembers([])
        }
        loadConversations()
      },
    })
  }

  const onGroupCreated = async (conv: Conversation) => {
    setCreateOpen(false)
    await loadConversations()
    openConversation(conv.id)
  }

  const activeConv = conversations.find((c) => c.id === activeId)

  // ── 会话列表（侧栏内容） ──
  const listContent = (
    <div className="gc-list">
      <Button
        type="primary"
        icon={<PlusOutlined />}
        block
        size="large"
        onClick={() => setCreateOpen(true)}
        className="gc-new-btn"
      >
        新建群聊
      </Button>
      {conversations.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="还没有群聊"
          style={{ marginTop: 48 }}
        />
      ) : (
        <div className="gc-conv-list">
          {conversations.map((c) => (
            <div
              key={c.id}
              className={`gc-conv ${activeId === c.id ? 'gc-conv--active' : ''}`}
              onClick={() => openConversation(c.id)}
            >
              <div className="gc-conv-icon">
                <TeamOutlined />
              </div>
              <span className="gc-conv-title">{c.title}</span>
              <DeleteOutlined
                className="gc-conv-del"
                onClick={(e) => {
                  e.stopPropagation()
                  handleDelete(c.id)
                }}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  )

  return (
    <div className="gc-page">
      {!isMobile && <div className="gc-sider">{listContent}</div>}
      {isMobile && (
        <Drawer
          placement="left"
          open={listOpen}
          onClose={() => setListOpen(false)}
          width={300}
          styles={{ body: { padding: 16 } }}
        >
          {listContent}
        </Drawer>
      )}

      <div className="gc-main">
        {/* 顶栏 */}
        <div className="gc-header">
          {isMobile && (
            <Button
              type="text"
              icon={<MenuOutlined />}
              onClick={() => setListOpen(true)}
            />
          )}
          {activeId ? (
            <div className="gc-header-info">
              <div className="gc-header-title-row">
                <span className="gc-header-title">{activeConv?.title || '群聊'}</span>
                <Tag bordered={false} className="gc-member-count">
                  {members.length} 位成员
                </Tag>
                {activeConv?.enable_tools && (
                  <Tag bordered={false} color="blue">
                    🛠 工具已开启
                  </Tag>
                )}
              </div>
              <div className="gc-header-members">
                {members.map((m) => (
                  <Tooltip key={m.id} title={m.name}>
                    <span className="gc-member-chip">
                      <PersonaAvatar
                        name={m.name}
                        avatarUrl={m.avatar_url}
                        size={22}
                      />
                      <span className="gc-member-chip-name">{m.name}</span>
                    </span>
                  </Tooltip>
                ))}
              </div>
            </div>
          ) : (
            <span className="gc-header-title">群聊</span>
          )}
          {activeId && (
            <Button
              type="text"
              icon={<ShareAltOutlined />}
              className="gc-share-btn"
              onClick={() => setShareOpen(true)}
            >
              {isMobile ? '' : '分享'}
            </Button>
          )}
        </div>

        {/* 消息区 */}
        <div className="gc-messages" ref={scrollRef}>
          <div className="gc-thread">
          {!activeId ? (
            <div className="gc-placeholder">
              <div className="gc-placeholder-icon">
                <TeamOutlined />
              </div>
              <p className="gc-placeholder-title">多角色群聊</p>
              <p className="gc-placeholder-desc">
                选择或新建一个群聊，让多个角色一起聊天、互相接话
              </p>
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => setCreateOpen(true)}
              >
                新建群聊
              </Button>
            </div>
          ) : loadingMsgs ? (
            <div style={{ textAlign: 'center', marginTop: 60 }}>
              <Spin />
            </div>
          ) : messages.length === 0 ? (
            <div className="gc-placeholder">
              <div className="gc-placeholder-icon">
                <TeamOutlined />
              </div>
              <p className="gc-placeholder-desc">
                群成员已就位，发个话题开始吧
                <br />
                可用 <b>@角色名</b> 指定谁来回答
              </p>
            </div>
          ) : (
            messages.map((m) => {
              if (m.role === 'user') {
                return (
                  <div key={m.id} className="gc-row gc-row--user">
                    <div className="gc-bubble gc-bubble--user">{m.content}</div>
                    <PersonaAvatar
                      name={user?.nickname || user?.username || '我'}
                      avatarUrl={user?.avatar}
                      size={38}
                      icon={<UserOutlined />}
                    />
                  </div>
                )
              }
              const member = m.senderPersonaId
                ? memberMap.get(m.senderPersonaId)
                : undefined
              const name = m.senderName || member?.name || 'AI'
              return (
                <div key={m.id} className="gc-row gc-row--ai">
                  <PersonaAvatar name={name} avatarUrl={member?.avatar_url} size={38} />
                  <div className="gc-ai-block">
                    <div className="gc-sender-name">{name}</div>
                    {m.toolRuns && m.toolRuns.length > 0 && (
                      <div className="gc-tool-chips">
                        {m.toolRuns.map((tr, idx) => {
                          const meta = resolveToolMeta(tr.tool)
                          return (
                            <span
                              key={idx}
                              className={`gc-tool-chip ${tr.status === 'running' ? 'gc-tool-chip--run' : ''}`}
                            >
                              {meta.icon} {meta.label}
                              {tr.status === 'running' && ' …'}
                            </span>
                          )
                        })}
                      </div>
                    )}
                    <div className="gc-bubble gc-bubble--ai">
                      {m.content ? (
                        <MarkdownMessage content={m.content} />
                      ) : (
                        <span className="gc-typing">
                          <i />
                          <i />
                          <i />
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              )
            })
          )}
          </div>
        </div>

        {/* 输入区 */}
        {activeId && (
          <div className="gc-input-wrap">
            <div className="gc-input-inner">
            {/* @ 提及下拉 */}
            {mentionOpen && mentionCandidates.length > 0 && (
              <div className="gc-mention-pop">
                <div className="gc-mention-hint">选择要 @ 的成员</div>
                {mentionCandidates.map((m, i) => (
                  <div
                    key={m.id}
                    className={`gc-mention-item ${i === mentionIndex ? 'gc-mention-item--on' : ''}`}
                    onMouseEnter={() => setMentionIndex(i)}
                    onMouseDown={(e) => {
                      e.preventDefault()
                      applyMention(m.name)
                    }}
                  >
                    <PersonaAvatar name={m.name} avatarUrl={m.avatar_url} size={26} />
                    <span>{m.name}</span>
                  </div>
                ))}
              </div>
            )}
            <div className="gc-input-bar">
              <Input.TextArea
                ref={inputRef}
                value={input}
                onChange={(e) => handleInputChange(e.target.value)}
                placeholder="说点什么…（输入 @ 可指定成员回答）"
                autoSize={{ minRows: 2, maxRows: 8 }}
                variant="borderless"
                className="gc-textarea"
                style={{ fontSize: 16, padding: 0, resize: 'none' }}
                onKeyDown={(e) => {
                  if (mentionOpen && mentionCandidates.length > 0) {
                    if (e.key === 'ArrowDown') {
                      e.preventDefault()
                      setMentionIndex((i) => (i + 1) % mentionCandidates.length)
                      return
                    }
                    if (e.key === 'ArrowUp') {
                      e.preventDefault()
                      setMentionIndex(
                        (i) =>
                          (i - 1 + mentionCandidates.length) %
                          mentionCandidates.length,
                      )
                      return
                    }
                    if (e.key === 'Enter' || e.key === 'Tab') {
                      e.preventDefault()
                      applyMention(mentionCandidates[mentionIndex].name)
                      return
                    }
                    if (e.key === 'Escape') {
                      setMentionOpen(false)
                      return
                    }
                  }
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    handleSend()
                  }
                }}
                disabled={sending}
              />
              <Button
                type="primary"
                shape="circle"
                icon={<SendOutlined />}
                loading={sending}
                onClick={handleSend}
                disabled={!input.trim()}
                className="gc-send-btn"
              />
            </div>
            <div className="gc-input-tip">
              Enter 发送 · Shift+Enter 换行 · @ 指定成员
            </div>
            </div>
          </div>
        )}
      </div>

      <CreateGroupModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={onGroupCreated}
      />
      <ShareModal
        open={shareOpen}
        conversationId={activeId ?? undefined}
        onClose={() => setShareOpen(false)}
      />
    </div>
  )
}

// ── 新建群聊弹窗：勾选 2~5 个角色卡 + 群名 ──
function CreateGroupModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: (conv: Conversation) => void
}) {
  const [personas, setPersonas] = useState<Persona[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [title, setTitle] = useState('')
  const [enableTools, setEnableTools] = useState(false)
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!open) return
    setSelected([])
    setTitle('')
    setEnableTools(false)
    setLoading(true)
    personaApi
      .list()
      .then((r) => setPersonas(r.data))
      .finally(() => setLoading(false))
  }, [open])

  const toggle = (id: string) => {
    setSelected((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id)
      if (prev.length >= 5) {
        antdMessage.warning('群成员最多 5 个')
        return prev
      }
      return [...prev, id]
    })
  }

  const handleOk = async () => {
    if (selected.length < 2) {
      antdMessage.warning('至少选择 2 个角色')
      return
    }
    setSubmitting(true)
    try {
      const resp = await groupApi.createGroup(
        selected,
        title.trim() || undefined,
        enableTools,
      )
      antdMessage.success('已创建群聊')
      onCreated(resp.data)
    } catch {
      antdMessage.error('创建失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title="新建群聊"
      open={open}
      onCancel={onClose}
      onOk={handleOk}
      okText={selected.length >= 2 ? `创建（${selected.length}）` : '创建'}
      cancelText="取消"
      confirmLoading={submitting}
      width={560}
    >
      <p style={{ color: '#667085', marginTop: 0 }}>
        选择 2~5 个角色卡组成群聊。提问后由「主持人」自动调度谁来回答，也可在对话里 @
        指定角色。
      </p>
      <Input
        placeholder="群名（可选，留空自动生成）"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        style={{ marginBottom: 16 }}
        maxLength={40}
      />
      <div className="gc-tools-toggle">
        <div>
          <div className="gc-tools-toggle-title">允许成员查资料</div>
          <div className="gc-tools-toggle-desc">
            开启后角色可调用知识库 / 记忆 / 联网 / MCP 工具，回答更慢但能查实时信息（默认关）
          </div>
        </div>
        <Switch checked={enableTools} onChange={setEnableTools} />
      </div>
      {loading ? (
        <div style={{ textAlign: 'center', padding: 24 }}>
          <Spin />
        </div>
      ) : personas.length === 0 ? (
        <Empty description="还没有角色卡，请先到 Agent 配置里创建" />
      ) : (
        <div className="gc-persona-grid">
          {personas.map((p) => {
            const checked = selected.includes(p.id)
            return (
              <div
                key={p.id}
                className={`gc-persona-card ${checked ? 'gc-persona-card--on' : ''}`}
                onClick={() => toggle(p.id)}
              >
                <Checkbox checked={checked} />
                <PersonaAvatar name={p.name} avatarUrl={p.avatar_url} size={40} />
                <div className="gc-persona-meta">
                  <div className="gc-persona-name">{p.name}</div>
                  <div className="gc-persona-desc">
                    {p.system_prompt?.slice(0, 30) || '（无设定）'}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </Modal>
  )
}
