import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Avatar,
  Button,
  Checkbox,
  Drawer,
  Dropdown,
  Empty,
  Input,
  Modal,
  Space,
  Spin,
  Switch,
  Tag,
  Tooltip,
  Upload,
  message as antdMessage,
} from 'antd'
import type { InputRef, MenuProps } from 'antd'
import {
  ArrowUpOutlined,
  CloseCircleFilled,
  CopyOutlined,
  DeleteOutlined,
  ExclamationCircleFilled,
  FormOutlined,
  LogoutOutlined,
  MenuOutlined,
  MoreOutlined,
  PictureOutlined,
  PlusOutlined,
  SendOutlined,
  ShareAltOutlined,
  StarFilled,
  StarOutlined,
  TeamOutlined,
  ToolOutlined,
  UsergroupAddOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import {
  chatApi,
  groupApi,
  subscribeGroupEvents,
  type Conversation,
  type GroupConversation,
  type GroupHuman,
  type GroupMember,
} from '@/api/chat'
import { personaApi, type Persona } from '@/api/personas'
import MarkdownMessage from '@/components/MarkdownMessage'
import { AuthenticatedImage } from '@/components/AuthenticatedImage'
import VoiceInputButton from '@/components/VoiceInputButton'
import { useAuthStore } from '@/stores/authStore'
import { useGroupHeaderStore } from '@/stores/groupHeaderStore'
import { copyText } from '@/utils/clipboard'
import { favoriteApi } from '@/api/favorites'
import { resolveToolMeta, formatMsgTime, splitBubbles, hasBubbleSep } from '@/pages/chat/types'
import ShareModal from '@/pages/chat/ShareModal'

// 群聊页内的消息模型（含流式态 + 发送者 + 工具调用标记）
interface GroupToolRun {
  tool: string
  query?: string
  status?: string
}

// 工具 chip 去重：同一工具多次调用合并成一个（带 ×次数），running 状态合并保留，
// 避免重复调用刷出一长串相同 chip。
function dedupToolRuns(
  runs: GroupToolRun[],
): { tool: string; count: number; running: boolean }[] {
  const map = new Map<string, { tool: string; count: number; running: boolean }>()
  for (const r of runs) {
    const e = map.get(r.tool)
    if (e) {
      e.count += 1
      if (r.status === 'running') e.running = true
    } else {
      map.set(r.tool, { tool: r.tool, count: 1, running: r.status === 'running' })
    }
  }
  return Array.from(map.values())
}
interface GroupUiMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  senderPersonaId?: string | null
  senderName?: string | null
  // 多人实时群聊：真人发送者
  senderUserId?: string | null
  isMe?: boolean
  toolRuns?: GroupToolRun[]
  images?: string[]
  streaming?: boolean
  createdAt?: string
}

// 把后端群聊历史消息转成页面消息模型（openConversation 与重连 resync 复用）
type RawGroupMsg = {
  id: string
  role: string
  content: string
  sender_persona_id?: string | null
  sender_name?: string | null
  sender_user_id?: string | null
  is_me?: boolean
  images?: string[]
  meta_data?: { tool_calls?: { tool: string; query?: string }[] } | null
  created_at?: string | null
}
function toUiMessage(m: RawGroupMsg): GroupUiMessage {
  return {
    id: m.id,
    role: m.role as 'user' | 'assistant',
    content: m.content,
    senderPersonaId: m.sender_persona_id,
    senderName: m.sender_name,
    senderUserId: m.sender_user_id,
    isMe: m.is_me,
    images: m.images,
    createdAt: m.created_at ?? undefined,
    toolRuns: m.meta_data?.tool_calls?.map((t) => ({
      tool: t.tool,
      query: t.query,
      status: 'success',
    })),
  }
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

// 群头像：仿微信群宫格合成。取前 1~4 个成员头像拼成方块；
// 成员没头像则用名字首字 + 主题色块补位。纯前端、不落库、成员变动自动跟随。
function GroupAvatar({
  members,
  size = 40,
}: {
  members: { name: string; avatar_url?: string | null }[]
  size?: number
}) {
  const list = members.slice(0, 4)
  if (list.length === 0) {
    return (
      <div
        className="gc-group-avatar gc-group-avatar--empty"
        style={{ width: size, height: size }}
      >
        <TeamOutlined />
      </div>
    )
  }
  // 单成员直接铺满
  if (list.length === 1) {
    return <PersonaAvatar name={list[0].name} avatarUrl={list[0].avatar_url} size={size} />
  }
  return (
    <div
      className={`gc-group-avatar gc-group-avatar--${list.length}`}
      style={{ width: size, height: size }}
    >
      {list.map((m, i) => (
        <div className="gc-group-avatar-cell" key={i}>
          {m.avatar_url ? (
            <AuthenticatedImage
              src={m.avatar_url}
              alt={m.name}
              style={{ width: '100%', height: '100%', objectFit: 'cover' }}
            />
          ) : (
            <span
              className="gc-group-avatar-letter"
              style={{ background: colorFor(m.name) }}
            >
              {m.name.slice(0, 1)}
            </span>
          )}
        </div>
      ))}
    </div>
  )
}

export default function GroupChatPage() {
  const isMobile = useIsMobile()
  const user = useAuthStore((s) => s.user)
  const [searchParams, setSearchParams] = useSearchParams()
  const [conversations, setConversations] = useState<GroupConversation[]>([])
  const [allPersonas, setAllPersonas] = useState<Persona[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<GroupUiMessage[]>([])
  const [members, setMembers] = useState<GroupMember[]>([])
  const [humans, setHumans] = useState<GroupHuman[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [pendingImages, setPendingImages] = useState<{ key: string; url: string }[]>(
    [],
  )
  const [uploading, setUploading] = useState(false)
  const [loadingMsgs, setLoadingMsgs] = useState(false)
  const [thinking, setThinking] = useState(false)
  const [listOpen, setListOpen] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [joinOpen, setJoinOpen] = useState(false)
  const [shareOpen, setShareOpen] = useState(false)
  const [inviteOpen, setInviteOpen] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<InputRef>(null)
  // 实时订阅控制：切换会话/卸载时 abort 旧连接
  const subRef = useRef<AbortController | null>(null)
  // 工具明细展开的消息 id 集合（默认折叠成「调用了 N 次工具」汇总条）
  const [expandedTools, setExpandedTools] = useState<Set<string>>(() => new Set())
  // 本地收藏态：msgId -> favoriteId（收藏成功后金星，可取消）
  const [favIds, setFavIds] = useState<Record<string, string>>({})

  const toggleTools = (id: string) =>
    setExpandedTools((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const onCopyMsg = async (text: string) => {
    const ok = await copyText((text || '').replace(/\s*\[\[next\]\]\s*/g, '\n'))
    if (ok) antdMessage.success('已复制')
    else antdMessage.error('复制失败')
  }

  const onFavMsg = async (m: GroupUiMessage) => {
    const existing = favIds[m.id]
    try {
      if (existing) {
        await favoriteApi.remove(existing)
        setFavIds((prev) => {
          const next = { ...prev }
          delete next[m.id]
          return next
        })
        antdMessage.success('已取消收藏')
      } else {
        const { data } = await favoriteApi.add('message', m.id, {
          title: `${m.senderName || 'AI'} 的发言`,
          summary: m.content.slice(0, 120),
          conversation_id: activeId ?? undefined,
          is_group: true,
        })
        setFavIds((prev) => ({ ...prev, [m.id]: data.id }))
        antdMessage.success('已收藏')
      }
    } catch (e) {
      antdMessage.error((e as Error).message)
    }
  }
  // 当前正在流式输出的 AI 气泡临时 id（speaker_start 设、speaker_end 清）
  const streamingRef = useRef<string | null>(null)
  // 已渲染过的真人消息 id 集合（say 乐观插入与 SSE 回声去重）
  const seenHumanRef = useRef<Set<string>>(new Set())

  // @ 提及下拉：是否显示 + 过滤关键字 + 高亮项
  const [mentionOpen, setMentionOpen] = useState(false)
  const [mentionKeyword, setMentionKeyword] = useState('')
  const [mentionIndex, setMentionIndex] = useState(0)

  const memberMap = useMemo(
    () => new Map(members.map((m) => [m.id, m])),
    [members],
  )

  // 真人成员头像/昵称映射（user_id -> {nickname, avatar_url}），渲染他人发言用
  const humanMap = useMemo(
    () => new Map(humans.map((h) => [h.user_id, h])),
    [humans],
  )

  const mentionCandidates = useMemo(() => {
    const kw = mentionKeyword.toLowerCase()
    return members.filter((m) => !kw || m.name.toLowerCase().includes(kw))
  }, [members, mentionKeyword])

  const loadConversations = async () => {
    const resp = await groupApi.listGroups()
    setConversations(resp.data)
    return resp.data
  }

  useEffect(() => {
    loadConversations()
    personaApi
      .list(true)
      .then((r) => setAllPersonas(r.data))
      .catch(() => {})
    // 卸载时断开实时订阅
    return () => {
      subRef.current?.abort()
    }
  }, [])

  // 支持 ?conv=xxx 深链直接打开（如加入群聊后跳转）
  useEffect(() => {
    const cid = searchParams.get('conv')
    if (cid && cid !== activeId) {
      openConversation(cid)
      searchParams.delete('conv')
      setSearchParams(searchParams, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  // persona id -> {name, avatar_url}，用于群头像宫格合成
  const personaMap = useMemo(
    () => new Map(allPersonas.map((p) => [p.id, p])),
    [allPersonas],
  )

  // 取某群聊的成员列表（用于宫格头像）：优先 member_persona_ids 顺序
  const membersForConv = (c: Conversation) => {
    const ids = ((c as Conversation & { member_persona_ids?: string[] })
      .member_persona_ids || []) as string[]
    return ids
      .map((id) => personaMap.get(id))
      .filter((p): p is Persona => !!p)
      .map((p) => ({ name: p.name, avatar_url: p.avatar_url }))
  }

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, thinking])

  const openConversation = async (id: string) => {
    // 断开旧订阅
    subRef.current?.abort()
    streamingRef.current = null
    seenHumanRef.current = new Set()
    setThinking(false)
    setActiveId(id)
    setListOpen(false)
    setLoadingMsgs(true)
    try {
      const [msgsResp, membersResp, humansResp] = await Promise.all([
        groupApi.listGroupMessages(id),
        groupApi.listMembers(id),
        groupApi.listHumans(id).catch(() => ({ data: [] as GroupHuman[] })),
      ])
      setMembers(membersResp.data)
      setHumans(humansResp.data)
      msgsResp.data.forEach((m) => {
        const su = (m as { sender_user_id?: string }).sender_user_id
        if (m.role === 'user' && su) seenHumanRef.current.add(m.id)
      })
      setMessages(msgsResp.data.map((m) => toUiMessage(m as RawGroupMsg)))
      startSubscription(id)
    } finally {
      setLoadingMsgs(false)
    }
  }

  // ── 实时订阅：接收全员发言与 AI 接话事件（带断线自动重连）──
  const startSubscription = (id: string) => {
    const ctrl = new AbortController()
    subRef.current = ctrl
    let attempt = 0
    let connectedOnce = false

    // 重连后补齐断线期间可能漏掉的消息与成员状态
    const resync = async () => {
      try {
        const [m, h] = await Promise.all([
          groupApi.listGroupMessages(id),
          groupApi.listHumans(id).catch(() => ({ data: [] as GroupHuman[] })),
        ])
        seenHumanRef.current = new Set()
        m.data.forEach((x) => {
          const su = (x as { sender_user_id?: string }).sender_user_id
          if (x.role === 'user' && su) seenHumanRef.current.add(x.id)
        })
        setMessages(m.data.map((x) => toUiMessage(x as RawGroupMsg)))
        setHumans(h.data)
        streamingRef.current = null
        setThinking(false)
      } catch {
        /* 补齐失败忽略，下条消息照常追加 */
      }
    }

    const refreshHumans = () => {
      groupApi
        .listHumans(id)
        .then((r) => setHumans(r.data))
        .catch(() => {})
    }

    // 定期刷新在线状态：兜底处理「网络硬断、对端没来得及广播离线」的情况
    const onlineTimer = setInterval(refreshHumans, 30000)
    ctrl.signal.addEventListener('abort', () => clearInterval(onlineTimer))

    const handlers = {
      onReady: () => {
        attempt = 0
        if (connectedOnce) resync() // 这是一次重连，补齐数据
        connectedOnce = true
        // 自己 SSE 已连上、服务端已标记在线，刷新一次在线状态（首连也刷）
        refreshHumans()
      },
      onThinking: () => setThinking(true),
      onPresence: (d: { type: string; nickname?: string }) => {
        if (d.type === 'join' || d.type === 'leave') {
          antdMessage.info(
            `${d.nickname} ${d.type === 'join' ? '加入了群聊' : '退出了群聊'}`,
          )
        }
        refreshHumans()
      },
      onHumanMessage: (d: {
        message_id: string
        user_id: string
        nickname: string
        content: string
      }) => {
        if (seenHumanRef.current.has(d.message_id)) return
        seenHumanRef.current.add(d.message_id)
        setMessages((prev) => [
          ...prev,
          {
            id: d.message_id,
            role: 'user' as const,
            content: d.content,
            senderUserId: d.user_id,
            senderName: d.nickname,
            isMe: d.user_id === user?.id,
            createdAt: new Date().toISOString(),
          },
        ])
      },
      onSpeakerStart: (d: { persona_id: string; name: string }) => {
        setThinking(false)
        const tempId = `s-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
        streamingRef.current = tempId
        setMessages((prev) => [
          ...prev,
          {
            id: tempId,
            role: 'assistant' as const,
            content: '',
            senderPersonaId: d.persona_id,
            senderName: d.name,
            streaming: true,
          },
        ])
      },
      onToken: (d: { text: string }) => {
        const cur = streamingRef.current
        if (!cur) return
        setMessages((prev) =>
          prev.map((m) => (m.id === cur ? { ...m, content: m.content + d.text } : m)),
        )
      },
      onToolStart: (d: { tool: string; query: string }) => {
        const cur = streamingRef.current
        if (!cur) return
        setMessages((prev) =>
          prev.map((m) =>
            m.id === cur
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
      onToolResult: (d: { tool: string; status?: string }) => {
        const cur = streamingRef.current
        if (!cur) return
        setMessages((prev) =>
          prev.map((m) => {
            if (m.id !== cur) return m
            const runs = [...(m.toolRuns || [])]
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
      onSpeakerEnd: (d: { message_id: string }) => {
        const cur = streamingRef.current
        setMessages((prev) =>
          prev.map((m) =>
            m.id === cur
              ? { ...m, id: d.message_id, streaming: false, createdAt: new Date().toISOString() }
              : m,
          ),
        )
        streamingRef.current = null
      },
      onDone: () => setThinking(false),
      onError: (msg: string) => {
        setThinking(false)
        antdMessage.error(msg)
      },
    }

    const scheduleReconnect = () => {
      attempt += 1
      const delay = Math.min(1000 * 2 ** attempt, 15000)
      setTimeout(() => {
        if (!ctrl.signal.aborted) connect()
      }, delay)
    }
    const connect = () => {
      subscribeGroupEvents(id, handlers, ctrl.signal)
        .then(() => {
          if (!ctrl.signal.aborted) scheduleReconnect()
        })
        .catch(() => {
          if (!ctrl.signal.aborted) scheduleReconnect()
        })
    }
    connect()
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

  const onInputKeyDown = (e: React.KeyboardEvent) => {
    if (mentionOpen && mentionCandidates.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setMentionIndex((i) => (i + 1) % mentionCandidates.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setMentionIndex(
          (i) => (i - 1 + mentionCandidates.length) % mentionCandidates.length,
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
  }

  const handleSend = async () => {
    const text = input.trim()
    if ((!text && pendingImages.length === 0) || !activeId || sending) return
    setInput('')
    setMentionOpen(false)
    setSending(true)
    const imgs = pendingImages
    setPendingImages([])
    // 本人消息也通过 SSE 回声统一渲染（避免乐观插入与回声重复）
    try {
      await groupApi.say(
        activeId,
        text || '（看图）',
        imgs.map((i) => i.key),
      )
      loadConversations()
    } catch {
      antdMessage.error('群聊发送失败')
      setInput(text)
    } finally {
      setSending(false)
    }
  }

  const handleUploadImage = async (file: File) => {
    setUploading(true)
    try {
      const { data } = await chatApi.uploadImage(file)
      setPendingImages((prev) => [...prev, { key: data.file_key, url: data.url }])
    } catch (e) {
      antdMessage.error((e as Error).message)
    } finally {
      setUploading(false)
    }
    return Upload.LIST_IGNORE
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

  // 开新对话：复用当前群成员组合 + 工具开关，新建一个空会话。
  // 标题用原群名传入，后端会自动去重加「（N）」编号区分。
  const handleNewSession = async () => {
    if (!activeConv) return
    const memberIds = (activeConv.member_persona_ids as string[]) || members.map((m) => m.id)
    if (memberIds.length < 2) {
      antdMessage.warning('当前群聊成员信息缺失，无法快速开新对话')
      return
    }
    const baseTitle = (activeConv.title || '群聊').replace(/（\d+）$/, '').trim()
    try {
      const resp = await groupApi.createGroup(memberIds, baseTitle, !!activeConv.enable_tools)
      await loadConversations()
      openConversation(resp.data.id)
      antdMessage.success('已开启新对话')
    } catch {
      antdMessage.error('开新对话失败')
    }
  }

  // 清空当前群聊的消息（保留群和成员）
  const handleClearMessages = () => {
    if (!activeId) return
    Modal.confirm({
      title: '清空当前群聊消息？',
      icon: <ExclamationCircleFilled style={{ color: '#FF5D34' }} />,
      content: '该群聊的所有对话记录将被清空，角色组合保留，此操作无法恢复。',
      okText: '清空',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          await groupApi.clearMessages(activeId)
          setMessages([])
          loadConversations()
          antdMessage.success('消息已清空')
        } catch {
          antdMessage.error('清空失败')
        }
      },
    })
  }

  const activeConv = conversations.find((c) => c.id === activeId)

  // 群主开/关本群工具（知识库/记忆/联网/MCP）。即时生效，下一轮 AI 发言按新值走。
  const handleToggleTools = async () => {
    if (!activeId || !activeConv) return
    const next = !activeConv.enable_tools
    try {
      await groupApi.setTools(activeId, next)
      setConversations((prev) =>
        prev.map((c) => (c.id === activeId ? { ...c, enable_tools: next } : c)),
      )
      antdMessage.success(
        next ? '已开启工具：角色可查知识库/记忆/联网/MCP' : '已关闭工具',
      )
    } catch (e) {
      antdMessage.error((e as Error).message)
    }
  }

  // 手机端：把群聊操作注册到全局顶栏（替代搜索框），并隐藏群聊自己的标题栏，合并成一条
  useEffect(() => {
    if (!isMobile || !activeId || !activeConv) {
      useGroupHeaderStore.getState().clear()
      return
    }
    const isOwner = !!activeConv.is_owner
    const items: MenuProps['items'] = isOwner
      ? [
          {
            key: 'tools',
            icon: <ToolOutlined />,
            label: activeConv.enable_tools
              ? '🛠 工具：已开启（点击关闭）'
              : '🛠 工具：已关闭（点击开启）',
            onClick: () => handleToggleTools(),
          },
          {
            key: 'new',
            icon: <FormOutlined />,
            label: '开新对话',
            onClick: () => handleNewSession(),
          },
          {
            key: 'clear',
            icon: <DeleteOutlined />,
            danger: true,
            label: '清空消息',
            onClick: () => handleClearMessages(),
          },
        ]
      : [
          {
            key: 'leave',
            icon: <LogoutOutlined />,
            danger: true,
            label: '退出群聊',
            onClick: () => handleLeave(),
          },
        ]
    useGroupHeaderStore.getState().register({
      title: activeConv.title || '群聊',
      openList: () => setListOpen(true),
      openInvite: () => setInviteOpen(true),
      openShare: () => setShareOpen(true),
      canShare: isOwner,
      moreItems: items,
    })
    return () => useGroupHeaderStore.getState().clear()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isMobile, activeId, activeConv?.is_owner, activeConv?.title, activeConv?.enable_tools])

  // 退出群聊（非群主）
  const handleLeave = () => {
    if (!activeId) return
    Modal.confirm({
      title: '退出该群聊？',
      icon: <ExclamationCircleFilled style={{ color: '#FF5D34' }} />,
      content: '退出后将不再接收该群聊消息，可凭邀请码重新加入。',
      okText: '退出',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          await groupApi.leave(activeId)
          subRef.current?.abort()
          setActiveId(null)
          setMessages([])
          setMembers([])
          setHumans([])
          loadConversations()
          antdMessage.success('已退出群聊')
        } catch {
          antdMessage.error('退出失败')
        }
      },
    })
  }

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
      <Button
        icon={<UsergroupAddOutlined />}
        block
        onClick={() => setJoinOpen(true)}
        style={{ marginTop: 4, marginBottom: 18 }}
      >
        输入邀请码加入
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
                <GroupAvatar members={c.avatar_members ?? membersForConv(c)} size={40} />
              </div>
              <span className="gc-conv-title">{c.title}</span>
              {c.is_owner === false && (
                <Tag bordered={false} color="green" style={{ marginRight: 4 }}>
                  已加入
                </Tag>
              )}
              {c.is_owner !== false && (
                <DeleteOutlined
                  className="gc-conv-del"
                  onClick={(e) => {
                    e.stopPropagation()
                    handleDelete(c.id)
                  }}
                />
              )}
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
        {isMobile && !activeId ? (
          /* 手机端未选中会话：直接铺已有群聊列表（新建按钮在列表顶部） */
          <div className="gc-mobile-list">{listContent}</div>
        ) : (
        <>
        {/* 顶栏（桌面端；手机端已合并进全局顶栏） */}
        {!isMobile && (
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
                <GroupAvatar
                  members={activeConv?.avatar_members ?? members}
                  size={32}
                />
                <span className="gc-header-title">{activeConv?.title || '群聊'}</span>
                {humans.length > 1 && (
                  <Tag bordered={false} color="green" className="gc-online-tag">
                    👥 {humans.filter((h) => h.online).length}/{humans.length} 在线
                  </Tag>
                )}
                <span className="gc-header-tags">
                  <Tag bordered={false} className="gc-member-count">
                    {members.length} 位成员
                  </Tag>
                  {activeConv?.enable_tools && (
                    <Tag bordered={false} color="blue">
                      🛠 工具已开启
                    </Tag>
                  )}
                </span>
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
            <div className="gc-header-actions">
              <Button
                type="text"
                icon={<UsergroupAddOutlined />}
                className="gc-share-btn"
                onClick={() => setInviteOpen(true)}
                title="邀请好友加入群聊一起聊"
              >
                {isMobile ? '' : '邀请'}
              </Button>
              {activeConv?.is_owner && (
                <Button
                  type="text"
                  icon={<FormOutlined />}
                  className="gc-share-btn"
                  onClick={handleNewSession}
                  title="复用当前角色组合，开启一个全新的空对话"
                >
                  {isMobile ? '' : '开新对话'}
                </Button>
              )}
              {activeConv?.is_owner && (
                <Button
                  type="text"
                  icon={<ShareAltOutlined />}
                  className="gc-share-btn"
                  onClick={() => setShareOpen(true)}
                >
                  {isMobile ? '' : '分享'}
                </Button>
              )}
              <Dropdown
                trigger={['click']}
                menu={{
                  items: [
                    ...(activeConv?.is_owner
                      ? [
                          {
                            key: 'tools',
                            icon: <ToolOutlined />,
                            label: activeConv.enable_tools
                              ? '🛠 工具：已开启（点击关闭）'
                              : '🛠 工具：已关闭（点击开启）',
                            onClick: handleToggleTools,
                          },
                          {
                            key: 'clear',
                            icon: <DeleteOutlined />,
                            danger: true,
                            label: '清空消息',
                            onClick: handleClearMessages,
                          },
                        ]
                      : []),
                    ...(activeConv && !activeConv.is_owner
                      ? [
                          {
                            key: 'leave',
                            icon: <LogoutOutlined />,
                            danger: true,
                            label: '退出群聊',
                            onClick: handleLeave,
                          },
                        ]
                      : []),
                  ],
                }}
              >
                <Button type="text" icon={<MoreOutlined />} className="gc-share-btn" />
              </Dropdown>
            </div>
          )}
        </div>
        )}

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
              <Space direction="vertical" size={10} style={{ alignItems: 'center' }}>
                <Button
                  type="primary"
                  icon={<PlusOutlined />}
                  onClick={() => setCreateOpen(true)}
                >
                  新建群聊
                </Button>
              </Space>
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
                // 其他真人成员的发言：靠左显示昵称 + 彩色头像
                if (m.isMe === false && m.senderUserId) {
                  const human = humanMap.get(m.senderUserId)
                  const nick = human?.nickname || m.senderName || '成员'
                  return (
                    <div key={m.id} className="gc-row gc-row--ai">
                      <PersonaAvatar
                        name={nick}
                        avatarUrl={human?.avatar_url}
                        size={38}
                        icon={<UserOutlined />}
                      />
                      <div className="gc-ai-block">
                        <div className="gc-sender-name">{nick}</div>
                        {m.images && m.images.length > 0 && (
                          <div className="gc-msg-images">
                            {m.images.map((url, i) => (
                              <AuthenticatedImage
                                key={i}
                                src={url}
                                alt=""
                                className="gc-msg-image"
                              />
                            ))}
                          </div>
                        )}
                        {m.content && (
                          <div className="gc-bubble gc-bubble--peer">{m.content}</div>
                        )}
                      </div>
                    </div>
                  )
                }
                return (
                  <div key={m.id} className="gc-row gc-row--user">
                    <div className="gc-user-block">
                      {m.images && m.images.length > 0 && (
                        <div className="gc-msg-images">
                          {m.images.map((url, i) => (
                            <AuthenticatedImage
                              key={i}
                              src={url}
                              alt=""
                              className="gc-msg-image"
                            />
                          ))}
                        </div>
                      )}
                      {m.content && (
                        <div className="gc-bubble gc-bubble--user">{m.content}</div>
                      )}
                      {m.content && m.createdAt && (
                        <div className="gc-msg-time gc-msg-time--me">
                          {formatMsgTime(m.createdAt)}
                        </div>
                      )}
                    </div>
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
                    {m.toolRuns && m.toolRuns.length > 0 && (() => {
                      const runs = dedupToolRuns(m.toolRuns)
                      const totalCalls = runs.reduce((s, r) => s + r.count, 0)
                      const running = runs.some((r) => r.running)
                      const open = running || expandedTools.has(m.id)
                      return (
                        <div className="gc-tool-area">
                          <span
                            className="gc-tool-summary"
                            onClick={() => !running && toggleTools(m.id)}
                            style={{ cursor: running ? 'default' : 'pointer' }}
                          >
                            <ToolOutlined />{' '}
                            {running ? '正在调用工具…' : `调用了 ${totalCalls} 次工具`}
                            {!running && <span className="gc-tool-caret">{open ? ' ▾' : ' ▸'}</span>}
                          </span>
                          {open && (
                            <div className="gc-tool-chips">
                              {runs.map((tr, idx) => {
                                const meta = resolveToolMeta(tr.tool)
                                return (
                                  <Tooltip key={idx} title={meta.label}>
                                    <span
                                      className={`gc-tool-chip ${tr.running ? 'gc-tool-chip--run' : ''}`}
                                    >
                                      {meta.icon} {meta.short}
                                      {tr.count > 1 && ` ×${tr.count}`}
                                      {tr.running && ' …'}
                                    </span>
                                  </Tooltip>
                                )
                              })}
                            </div>
                          )}
                        </div>
                      )
                    })()}
                    {m.content ? (
                      hasBubbleSep(m.content) ? (
                        <div
                          style={{
                            display: 'flex',
                            flexDirection: 'column',
                            gap: 6,
                            alignItems: 'flex-start',
                          }}
                        >
                          {splitBubbles(m.content).map((seg, i) => (
                            <div key={i} className="gc-bubble gc-bubble--ai">
                              <MarkdownMessage content={seg} />
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="gc-bubble gc-bubble--ai">
                          <MarkdownMessage content={m.content} />
                        </div>
                      )
                    ) : (
                      <div className="gc-bubble gc-bubble--ai">
                        <span className="gc-typing">
                          <i />
                          <i />
                          <i />
                        </span>
                      </div>
                    )}
                    {m.createdAt && !m.streaming && (
                      <div className="gc-ai-actions">
                        {m.content && (
                          <>
                            <Button
                              size="small"
                              type="text"
                              icon={<CopyOutlined />}
                              onClick={() => onCopyMsg(m.content)}
                              style={{ color: '#667085', fontSize: 12 }}
                            >
                              复制
                            </Button>
                            <Button
                              size="small"
                              type="text"
                              icon={
                                favIds[m.id] ? (
                                  <StarFilled style={{ color: '#FAAD14' }} />
                                ) : (
                                  <StarOutlined />
                                )
                              }
                              onClick={() => onFavMsg(m)}
                              style={{ color: favIds[m.id] ? '#FAAD14' : '#667085', fontSize: 12 }}
                            >
                              {favIds[m.id] ? '已收藏' : '收藏'}
                            </Button>
                          </>
                        )}
                        <span className="gc-msg-time">{formatMsgTime(m.createdAt)}</span>
                      </div>
                    )}
                  </div>
                </div>
              )
            })
          )}
          {thinking && (
            <div className="gc-row gc-row--ai gc-thinking-row">
              <div className="gc-thinking">
                <span className="gc-typing">
                  <i />
                  <i />
                  <i />
                </span>
                <span className="gc-thinking-text">AI 正在想怎么接话…</span>
              </div>
            </div>
          )}
          </div>
        </div>

        {/* 输入区 */}
        {activeId && (
          <div className="gc-input-wrap">
            <div className="gc-input-inner">
            {/* 待发送图片预览 */}
            {pendingImages.length > 0 && (
              <div className="gc-pending-images">
                {pendingImages.map((img, i) => (
                  <div key={i} className="gc-pending-image">
                    <AuthenticatedImage src={img.url} alt="" />
                    <CloseCircleFilled
                      className="gc-pending-del"
                      onClick={() =>
                        setPendingImages((prev) => prev.filter((_, idx) => idx !== i))
                      }
                    />
                  </div>
                ))}
              </div>
            )}
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
            {isMobile ? (
              // 手机端：单行紧凑 —— [🖼图片] [输入框] [↑发送]
              <div className="gc-input-box gc-input-box--mobile">
                <Upload
                  accept="image/*"
                  showUploadList={false}
                  beforeUpload={handleUploadImage}
                  disabled={uploading || sending}
                >
                  <Button
                    type="text"
                    shape="circle"
                    icon={<PictureOutlined style={{ fontSize: 18 }} />}
                    loading={uploading}
                    style={{ flexShrink: 0 }}
                  />
                </Upload>
                <VoiceInputButton
                  size={18}
                  onResult={(t) => setInput((prev) => (prev ? prev + ' ' + t : t))}
                />
                <Input.TextArea
                  ref={inputRef}
                  value={input}
                  onChange={(e) => handleInputChange(e.target.value)}
                  placeholder="说点什么…"
                  autoSize={{ minRows: 1, maxRows: 4 }}
                  variant="borderless"
                  className="gc-textarea"
                  style={{ fontSize: 16, padding: '4px 0', resize: 'none', flex: 1 }}
                  onKeyDown={onInputKeyDown}
                  disabled={sending}
                />
                <Button
                  type="primary"
                  shape="circle"
                  icon={<ArrowUpOutlined />}
                  loading={sending}
                  onClick={handleSend}
                  disabled={!input.trim() && pendingImages.length === 0}
                  style={{ flexShrink: 0 }}
                />
              </div>
            ) : (
            <div className="gc-input-box">
              <Input.TextArea
                ref={inputRef}
                value={input}
                onChange={(e) => handleInputChange(e.target.value)}
                placeholder="说点什么…（输入 @ 可指定成员回答）"
                autoSize={{ minRows: 1, maxRows: 6 }}
                variant="borderless"
                className="gc-textarea"
                style={{ fontSize: 16, padding: 0, resize: 'none' }}
                onKeyDown={onInputKeyDown}
                disabled={sending}
              />
              <div className="gc-input-toolbar">
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <Upload
                    accept="image/*"
                    showUploadList={false}
                    beforeUpload={handleUploadImage}
                    disabled={uploading || sending}
                  >
                    <Tooltip title="上传图片（每个角色看图发言）">
                      <Button
                        type="text"
                        icon={<PictureOutlined style={{ fontSize: 19 }} />}
                        loading={uploading}
                      />
                    </Tooltip>
                  </Upload>
                  <VoiceInputButton
                    onResult={(t) => setInput((prev) => (prev ? prev + ' ' + t : t))}
                  />
                </span>
                <Button
                  type="primary"
                  size="large"
                  icon={<SendOutlined />}
                  loading={sending}
                  onClick={handleSend}
                  disabled={!input.trim() && pendingImages.length === 0}
                  className="gc-send-btn"
                >
                  发送
                </Button>
              </div>
            </div>
            )}
            {!isMobile && (
              <div className="gc-input-tip">
                Enter 发送 · Shift+Enter 换行 · @ 指定成员
              </div>
            )}
            </div>
          </div>
        )}
        </>
        )}
      </div>

      <CreateGroupModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={onGroupCreated}
      />
      <JoinByCodeModal
        open={joinOpen}
        onClose={() => setJoinOpen(false)}
        onJoined={async (conv) => {
          setJoinOpen(false)
          await loadConversations()
          openConversation(conv.id)
        }}
      />
      <ShareModal
        open={shareOpen}
        conversationId={activeId ?? undefined}
        onClose={() => setShareOpen(false)}
      />
      <InviteModal
        open={inviteOpen}
        conversationId={activeId ?? undefined}
        isOwner={!!activeConv?.is_owner}
        humans={humans}
        onClose={() => setInviteOpen(false)}
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
      <p style={{ color: '#667085', marginTop: 0, marginBottom: 18, lineHeight: 1.7 }}>
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
        <Empty description="还没有角色卡，请先到 角色配置 里创建" />
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

// ── 邀请弹窗：群主生成/复制邀请链接、重置邀请码；展示在群真人成员 ──
function InviteModal({
  open,
  conversationId,
  isOwner,
  humans,
  onClose,
}: {
  open: boolean
  conversationId?: string
  isOwner: boolean
  humans: GroupHuman[]
  onClose: () => void
}) {
  const [code, setCode] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open || !conversationId || !isOwner) return
    setLoading(true)
    groupApi
      .getInvite(conversationId)
      .then((r) => setCode(r.data.join_code))
      .catch(() => antdMessage.error('获取邀请码失败'))
      .finally(() => setLoading(false))
  }, [open, conversationId, isOwner])

  const link = code ? `${window.location.origin}/groups/join/${code}` : ''

  const copy = async (text: string) => {
    const ok = await copyText(text)
    if (ok) antdMessage.success('已复制')
    else antdMessage.warning('复制失败，请长按上方文本手动复制')
  }

  const reset = async () => {
    if (!conversationId) return
    setLoading(true)
    try {
      const r = await groupApi.resetInvite(conversationId)
      setCode(r.data.join_code)
      antdMessage.success('邀请码已重置，旧链接失效')
    } catch {
      antdMessage.error('重置失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal
      title="邀请好友加入群聊"
      open={open}
      onCancel={onClose}
      footer={null}
      width={460}
    >
      {isOwner ? (
        <Spin spinning={loading}>
          <p style={{ color: '#667085', marginTop: 0, lineHeight: 1.7 }}>
            把链接发给好友（需注册并登录），即可加入这个群聊，和你及群里的 AI 角色一起实时开聊。
          </p>
          <div className="gc-invite-row">
            <Input value={link} readOnly />
            <Button type="primary" onClick={() => copy(link)} disabled={!link}>
              复制链接
            </Button>
          </div>
          <div className="gc-invite-row" style={{ marginTop: 10 }}>
            <Input value={code} readOnly addonBefore="邀请码" />
            <Button onClick={() => copy(code)} disabled={!code}>
              复制码
            </Button>
          </div>
          <Button type="link" danger onClick={reset} style={{ paddingLeft: 0 }}>
            重置邀请码（旧链接将失效）
          </Button>
        </Spin>
      ) : (
        <p style={{ color: '#667085', marginTop: 0 }}>
          只有群主可以生成邀请链接。
        </p>
      )}
      <div className="gc-invite-humans">
        <div className="gc-invite-humans-title">在群的人（{humans.length}）</div>
        <Space wrap size={[8, 8]}>
          {humans.map((h) => (
            <Tag key={h.user_id} bordered={false} color={h.role === 'owner' ? 'blue' : undefined}>
              <span
                className={`gc-online-dot ${h.online ? 'gc-online-dot--on' : ''}`}
              />
              {h.nickname}
              {h.role === 'owner' ? ' · 群主' : ''}
              {h.is_me ? ' · 我' : ''}
            </Tag>
          ))}
        </Space>
      </div>
    </Modal>
  )
}

// ── 输入邀请码加入群聊弹窗（支持粘贴邀请码或完整邀请链接）──
function JoinByCodeModal({
  open,
  onClose,
  onJoined,
}: {
  open: boolean
  onClose: () => void
  onJoined: (conv: Conversation) => void
}) {
  const [code, setCode] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (open) setCode('')
  }, [open])

  // 从输入里提取邀请码：兼容直接粘贴完整链接 .../groups/join/XXXX
  const extractCode = (raw: string): string => {
    const t = raw.trim()
    const m = t.match(/\/groups\/join\/([A-Za-z0-9]+)/)
    return (m ? m[1] : t).trim()
  }

  const handleOk = async () => {
    const c = extractCode(code)
    if (!c) {
      antdMessage.warning('请输入邀请码')
      return
    }
    setLoading(true)
    try {
      const resp = await groupApi.join(c)
      antdMessage.success('已加入群聊')
      onJoined(resp.data)
    } catch (e) {
      antdMessage.error((e as Error).message || '加入失败，邀请码可能无效或已失效')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal
      title="输入邀请码加入群聊"
      open={open}
      onCancel={onClose}
      onOk={handleOk}
      okText="加入"
      cancelText="取消"
      confirmLoading={loading}
      width={440}
    >
      <p style={{ color: '#667085', marginTop: 0, marginBottom: 14, lineHeight: 1.7 }}>
        粘贴好友给你的邀请码（或完整邀请链接）即可加入，和大家及群里的 AI 角色一起聊。
      </p>
      <Input
        placeholder="如 A6VMQAH7，或粘贴邀请链接"
        value={code}
        onChange={(e) => setCode(e.target.value)}
        onPressEnter={handleOk}
        size="large"
        allowClear
        autoFocus
      />
    </Modal>
  )
}
