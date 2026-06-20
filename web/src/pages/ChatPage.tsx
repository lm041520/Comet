import { useEffect, useRef, useState, type DragEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Button,
  Drawer,
  Input,
  Popconfirm,
  Popover,
  Space,
  Switch,
  Tooltip,
  Upload,
  message as antdMessage,
} from 'antd'
import {
  ArrowUpOutlined,
  DeleteOutlined,
  DownOutlined,
  FileTextOutlined,
  GlobalOutlined,
  CloseOutlined,
  PaperClipOutlined,
  PictureOutlined,
  PlusOutlined,
  RightOutlined,
  SendOutlined,
  ShareAltOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import {
  chatApi,
  streamChat,
  regenerateMessage,
  subscribeChatEvents,
  type Conversation,
  type ChatMessage,
  type ToolCall,
  type ToolRunStatus,
} from '@/api/chat'
import { favoriteApi } from '@/api/favorites'
import { AuthenticatedImage } from '@/components/AuthenticatedImage'
import VoiceInputButton from '@/components/VoiceInputButton'
import MessageItem from './chat/MessageItem'
import SelectionPopover from './chat/SelectionPopover'
import ShareModal from './chat/ShareModal'
import type { ChatAvatars, UiMessage } from './chat/types'
import { groupConversationsByDate } from './chat/groupByDate'
import { useMusicStore } from '@/stores/musicStore'
import { useChatHeaderStore } from '@/stores/chatHeaderStore'
import { personaApi } from '@/api/personas'
import { agentConfigApi } from '@/api/agentConfig'
import { authApi } from '@/api/auth'
import { useSkillStore } from '@/stores/skillStore'

export default function ChatPage() {
  const [params, setParams] = useSearchParams()
  const [conversations, setConversations] = useState<Conversation[]>([])
  // 折叠的日期分组（key 集合）；默认仅展开「今天」，其余折叠
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set())
  const [activeId, setActiveId] = useState<string | undefined>()
  const [messages, setMessages] = useState<UiMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [webSearch, setWebSearch] = useState(false)
  const [activeSkillId, setActiveSkillId] = useState<string | null>(null)
  const [pendingImages, setPendingImages] = useState<{ key: string; url: string }[]>([])
  const [pendingFiles, setPendingFiles] = useState<
    { file_name: string; text: string }[]
  >([])
  const [dragOver, setDragOver] = useState(false)
  const dragCounter = useRef(0)
  const [highlightId, setHighlightId] = useState<string | null>(null)
  // 对话头像上下文（角色头像 + 用户头像 + 总开关）
  const [avatars, setAvatars] = useState<ChatAvatars>({ show: false })
  // 移动端：会话列表收进抽屉，对话区占满
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== 'undefined' && window.innerWidth <= 768,
  )
  const [convDrawerOpen, setConvDrawerOpen] = useState(false)
  const [shareOpen, setShareOpen] = useState(false)
  // 播放器可见时，输入区在手机上需上移避让
  const playerVisible = useMusicStore((s) => s.visible)
  // 技能（任务能力包）：对话中可挂载/切换
  const skills = useSkillStore((s) => s.list)
  const ensureSkillsLoaded = useSkillStore((s) => s.ensureLoaded)
  useEffect(() => {
    ensureSkillsLoaded()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const activeSkill = skills.find((s) => s.id === activeSkillId) ?? null
  // 只在对话框技能选择器展示「已开启显示」的技能，避免技能多时拥挤
  const visibleSkills = skills.filter((s) => s.enabled)
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 768px)')
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])
  // 组件卸载：断开发送流与续传订阅（后台生成不受影响，照常落库）
  useEffect(() => {
    return () => {
      sendAbortRef.current?.abort()
      resumeAbortRef.current?.abort()
    }
  }, [])
  const scrollRef = useRef<HTMLDivElement>(null)
  const msgRefs = useRef<Record<string, HTMLDivElement | null>>({})
  const inputRef = useRef<{ focus: () => void } | null>(null)
  const pendingGreetingRef = useRef<string | null>(null)
  const groupsInited = useRef(false)
  // 发送流 / 续传订阅的中断控制器：组件卸载或切会话时断开（后台生成不受影响照常落库）
  const sendAbortRef = useRef<AbortController | null>(null)
  const resumeAbortRef = useRef<AbortController | null>(null)

  const convGroups = groupConversationsByDate(conversations)

  const startToolRun = (messageId: string, tc: ToolCall) => {
    setMessages((prev) =>
      prev.map((m) => {
        if (m.id !== messageId) return m
        const toolRuns = m.toolRuns ?? []
        const nextRun = {
          id: `${tc.tool}-${toolRuns.length}-${Date.now()}`,
          tool: tc.tool,
          query: tc.query,
          status: 'running' as const,
        }
        return {
          ...m,
          toolRuns: [...toolRuns, nextRun],
          toolCalls: [...(m.toolCalls ?? []), tc],
        }
      }),
    )
  }

  const finishToolRun = (
    messageId: string,
    tc: ToolCall & {
      status?: ToolRunStatus
      text?: string
      stats?: Record<string, unknown>
      latency_ms?: number
    },
  ) => {
    setMessages((prev) =>
      prev.map((m) => {
        if (m.id !== messageId) return m
        const toolRuns = m.toolRuns ?? []
        const idx = [...toolRuns]
          .reverse()
          .findIndex(
            (run) =>
              run.status === 'running' &&
              run.tool === tc.tool &&
              (!tc.query || run.query === tc.query),
          )
        if (idx < 0) return m
        const targetIndex = toolRuns.length - 1 - idx
        return {
          ...m,
          toolRuns: toolRuns.map((run, i) =>
            i === targetIndex
              ? {
                  ...run,
                  status: tc.status ?? 'success',
                  result: tc.text,
                  stats: tc.stats,
                  latencyMs: tc.latency_ms,
                }
              : run,
          ),
        }
      }),
    )
  }

  const settleRunningToolRuns = (messageId: string, status: ToolRunStatus) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === messageId
          ? {
              ...m,
              toolRuns: m.toolRuns?.map((run) =>
                run.status === 'running' ? { ...run, status } : run,
              ),
            }
          : m,
      ),
    )
  }

  // 首次拿到会话时，默认仅展开「今天」，其余分组折叠
  useEffect(() => {
    if (groupsInited.current || conversations.length === 0) return
    groupsInited.current = true
    const toCollapse = convGroups
      .filter((g) => g.key !== 'today')
      .map((g) => g.key)
    setCollapsedGroups(new Set(toCollapse))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversations])

  const toggleGroup = (key: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const loadConversations = async () => {
    try {
      const { data } = await chatApi.listConversations()
      // 单聊列表排除群聊会话（is_group），群聊在「群聊」页单独管理
      setConversations(
        (data as (Conversation & { is_group?: boolean })[]).filter((c) => !c.is_group),
      )
    } catch (e) {
      antdMessage.error((e as Error).message)
    }
  }

  useEffect(() => {
    loadConversations()
  }, [])

  // 重进对话页：默认打开「上次的对话」（最近一条），而不是新开空白会话。
  // 有深链(?conversation/greeting/message)或已选中会话时不抢。仅在首次会话到位时执行一次。
  const autoOpenedRef = useRef(false)
  useEffect(() => {
    if (autoOpenedRef.current || conversations.length === 0) return
    autoOpenedRef.current = true
    if (activeId) return
    if (params.get('conversation') || params.get('greeting') || params.get('message')) return
    openConversation(conversations[0].id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversations])

  // 加载对话头像上下文：当前角色头像 + 用户头像 + 显示开关
  const loadAvatars = async () => {
    try {
      const [pResp, cResp, meResp] = await Promise.all([
        personaApi.list(),
        agentConfigApi.get(),
        authApi.me(),
      ])
      const active = pResp.data.find((p) => p.is_active)
      setAvatars({
        show: cResp.data.show_avatar,
        personaName: active?.name,
        personaAvatarUrl: active?.avatar_url ?? null,
        userAvatarUrl: meResp.data.avatar ?? null,
        humanMode: cResp.data.human_mode,
      })
    } catch {
      // 头像信息拉取失败不影响对话
    }
  }

  useEffect(() => {
    loadAvatars()
  }, [])

  // 读取联网搜索工具的默认启停（来自「工具配置」），作为对话联网开关默认值
  useEffect(() => {
    import('@/api/tools').then(({ toolsApi }) => {
      toolsApi
        .list()
        .then(({ data }) => {
          const web = data.find((t) => t.tool_key === 'web_search')
          if (web) setWebSearch(web.enabled)
        })
        .catch(() => {
          // 取配置失败则保持默认关闭，不影响对话
        })
    })
  }, [])

  // 收藏深链：?conversation=&message= 打开会话并定位消息
  useEffect(() => {
    const conv = params.get('conversation')
    const msg = params.get('message')
    const greeting = params.get('greeting')
    if (conv) {
      openConversation(conv, msg ?? undefined)
      setParams({}, { replace: true })
    } else if (greeting) {
      // 从今日回顾「聊聊」跳来：AI 主动开场，把关怀句作为 AI 第一句话显示，输入框留空待用户回应。
      // 记下开场白，用户首次发言时带给后端落库进历史，模型才能接住这个话题。
      newConversation()
      pendingGreetingRef.current = greeting
      setMessages([
        {
          id: `greet-${Date.now()}`,
          role: 'assistant',
          content: greeting,
          createdAt: new Date().toISOString(),
        },
      ])
      setParams({}, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (highlightId) return // 深链定位时不强制滚到底
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, highlightId])

  const openConversation = async (id: string, focusMessageId?: string) => {
    setActiveId(id)
    setConvDrawerOpen(false)
    // 切会话：断开上一个会话的续传订阅
    resumeAbortRef.current?.abort()
    resumeAbortRef.current = null
    try {
      const [{ data }, favResp] = await Promise.all([
        chatApi.listMessages(id),
        favoriteApi.list('message'),
      ])
      const favByMsg: Record<string, string> = {}
      favResp.data.forEach((f) => {
        favByMsg[f.target_id] = f.id
      })
      setMessages(
        data.map((m: ChatMessage) => ({
          id: m.id,
          role: m.role as 'user' | 'assistant',
          content: m.content,
          citations: m.meta_data?.citations,
          toolCalls: m.meta_data?.tool_calls,
          images: m.images,
          attachments: m.meta_data?.attachments?.map((a) => ({
            file_name: a.file_name,
          })),
          conversationId: id,
          favId: favByMsg[m.id] ?? null,
          feedback: m.feedback ?? null,
          createdAt: m.created_at,
          fromHistory: true,
        })),
      )
      if (focusMessageId) {
        setHighlightId(focusMessageId)
        // 等渲染后滚动定位
        setTimeout(() => {
          msgRefs.current[focusMessageId]?.scrollIntoView({
            behavior: 'smooth',
            block: 'center',
          })
          setTimeout(() => setHighlightId(null), 2500)
        }, 200)
      }
      // 若该会话正有「后台生成」在进行（上次切走/刷新时未结束），订阅续传补全
      if (!focusMessageId) {
        const lastRole = data.length ? data[data.length - 1].role : undefined
        subscribeResume(id, lastRole === 'user')
      }
    } catch (e) {
      antdMessage.error((e as Error).message)
    }
  }

  // 断线重连续传：订阅会话进行中的生成，补推已生成内容并续接后续 token。
  // 没有进行中的生成时后端发 idle，本函数静默结束。
  // maybePending：进入时最后一条是用户消息（回答可能正在生成或刚落库），idle 时补拉一次历史兜底。
  const subscribeResume = (convId: string, maybePending = false) => {
    const controller = new AbortController()
    resumeAbortRef.current = controller
    const resumeMsgId = `resume-${convId}-${Date.now()}`
    let started = false
    const ensurePlaceholder = (content: string) => {
      if (started) return
      started = true
      setSending(true)
      setMessages((prev) => [
        ...prev,
        {
          id: resumeMsgId,
          role: 'assistant',
          content,
          toolCalls: [],
          toolRuns: [],
          streaming: true,
          conversationId: convId,
        },
      ])
    }
    subscribeChatEvents(
      convId,
      {
        onResume: (d) => {
          ensurePlaceholder(d.content || '')
          if (d.citations?.length) {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === resumeMsgId ? { ...m, citations: d.citations } : m,
              ),
            )
          }
        },
        onToken: (t) => {
          ensurePlaceholder('')
          setMessages((prev) =>
            prev.map((m) =>
              m.id === resumeMsgId ? { ...m, content: m.content + t } : m,
            ),
          )
        },
        onToolStart: (tc) => {
          ensurePlaceholder('')
          startToolRun(resumeMsgId, tc)
        },
        onToolResult: (tc) => finishToolRun(resumeMsgId, tc),
        onCitation: (cites) => {
          setMessages((prev) =>
            prev.map((m) => (m.id === resumeMsgId ? { ...m, citations: cites } : m)),
          )
        },
        onDone: (d) => {
          settleRunningToolRuns(resumeMsgId, 'success')
          setMessages((prev) =>
            prev.map((m) =>
              m.id === resumeMsgId
                ? {
                    ...m,
                    streaming: false,
                    id: d.message_id ?? m.id,
                    conversationId: d.conversation_id,
                    createdAt: m.createdAt ?? new Date().toISOString(),
                  }
                : m,
            ),
          )
          setSending(false)
          loadConversations()
        },
        onIdle: () => {
          // 没有进行中的生成：若进入时最后一条是用户消息，回答可能在「读历史→订阅」
          // 间隙刚落库，补拉一次历史兜底（仅当该会话仍是当前会话）。
          if (maybePending && !controller.signal.aborted) {
            setTimeout(() => {
              if (controller.signal.aborted) return
              chatApi
                .listMessages(convId)
                .then(({ data }) => {
                  if (controller.signal.aborted) return
                  const last = data[data.length - 1]
                  if (last && last.role === 'assistant') {
                    setMessages((prev) =>
                      prev.some((m) => m.id === last.id)
                        ? prev
                        : [
                            ...prev,
                            {
                              id: last.id,
                              role: 'assistant',
                              content: last.content,
                              citations: last.meta_data?.citations,
                              toolCalls: last.meta_data?.tool_calls,
                              conversationId: convId,
                              feedback: last.feedback ?? null,
                              createdAt: last.created_at,
                            },
                          ],
                    )
                  }
                })
                .catch(() => {})
            }, 600)
          }
        },
        onError: (msg) => {
          if (!started) return
          settleRunningToolRuns(resumeMsgId, 'error')
          setMessages((prev) =>
            prev.map((m) =>
              m.id === resumeMsgId
                ? { ...m, content: m.content || `⚠️ ${msg}`, streaming: false }
                : m,
            ),
          )
          setSending(false)
        },
      },
      controller.signal,
    )
  }

  const newConversation = () => {
    setActiveId(undefined)
    setMessages([])
    setConvDrawerOpen(false)
    resumeAbortRef.current?.abort()
    resumeAbortRef.current = null
  }

  // 手机端：把「会话历史 / 新对话」操作注册到全局顶栏（替代搜索框，合并成一行）
  const registerChatHeader = useChatHeaderStore((s) => s.register)
  const clearChatHeader = useChatHeaderStore((s) => s.clear)
  const setCanShare = useChatHeaderStore((s) => s.setCanShare)
  useEffect(() => {
    registerChatHeader({
      openHistory: () => setConvDrawerOpen(true),
      newChat: newConversation,
      openShare: () => setShareOpen(true),
    })
    return () => clearChatHeader()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  // 同步「当前会话是否可分享」给顶栏（手机端分享按钮显隐）
  useEffect(() => {
    setCanShare(!!activeId && messages.length > 0)
  }, [activeId, messages.length, setCanShare])

  // 重新生成某条 AI 回复：替换该条消息内容，重新流式
  const onRegenerate = async (target: UiMessage) => {
    if (sending) return
    setSending(true)
    setMessages((prev) =>
      prev.map((m) =>
        m.id === target.id
          ? {
              ...m,
              content: '',
              toolCalls: [],
              toolRuns: [],
              citations: undefined,
              streaming: true,
              feedback: null,
            }
          : m,
      ),
    )
    const aiId = target.id
    await regenerateMessage(aiId, {
      onToken: (t) => {
        setMessages((prev) =>
          prev.map((m) => (m.id === aiId ? { ...m, content: m.content + t } : m)),
        )
      },
      onToolStart: (tc) => startToolRun(aiId, tc),
      onToolResult: (tc) => finishToolRun(aiId, tc),
      onCitation: (cites) => {
        setMessages((prev) =>
          prev.map((m) => (m.id === aiId ? { ...m, citations: cites } : m)),
        )
      },
      onDone: (d) => {
        settleRunningToolRuns(aiId, 'success')
        setMessages((prev) =>
          prev.map((m) =>
            m.id === aiId
              ? { ...m, streaming: false, id: d.message_id ?? m.id, createdAt: new Date().toISOString() }
              : m,
          ),
        )
        setSending(false)
      },
      onError: (msg) => {
        settleRunningToolRuns(aiId, 'error')
        setMessages((prev) =>
          prev.map((m) =>
            m.id === aiId ? { ...m, content: `⚠️ ${msg}`, streaming: false } : m,
          ),
        )
        setSending(false)
      },
    })
  }

  const onDeleteConversation = async (id: string) => {
    try {
      await chatApi.deleteConversation(id)
      if (id === activeId) newConversation()
      loadConversations()
    } catch (e) {
      antdMessage.error((e as Error).message)
    }
  }

  const onUploadImage = async (file: File) => {
    try {
      const { data } = await chatApi.uploadImage(file)
      setPendingImages((prev) => [...prev, { key: data.file_key, url: data.url }])
    } catch (e) {
      antdMessage.error((e as Error).message)
    }
    return Upload.LIST_IGNORE // 阻止 antd 默认上传 + 不入 fileList（避免移动端选择器残留）
  }

  const onUploadFile = async (file: File) => {
    const hide = antdMessage.loading(`正在解析「${file.name}」…`, 0)
    try {
      const { data } = await chatApi.uploadFile(file)
      hide()
      setPendingFiles((prev) => [...prev, { file_name: data.file_name, text: data.text }])
      if (data.truncated) {
        antdMessage.warning(`文档较大，已截取前 ${data.chars} 字用于本次对话`)
      } else {
        antdMessage.success(`已附加「${data.file_name}」`)
      }
    } catch (e) {
      hide()
      antdMessage.error((e as Error).message)
    }
    return Upload.LIST_IGNORE // 阻止 antd 默认上传 + 不入 fileList
  }

  // 拖拽到对话区上传：图片走多模态，文档走临时附件，按扩展名/类型分流
  const DOC_EXTS = ['.pdf', '.docx', '.md', '.markdown', '.txt', '.html', '.htm']
  const handleDroppedFiles = async (files: FileList) => {
    for (const file of Array.from(files)) {
      const isImage = file.type.startsWith('image/')
      const lower = file.name.toLowerCase()
      const isDoc = DOC_EXTS.some((ext) => lower.endsWith(ext))
      if (isImage) {
        await onUploadImage(file)
      } else if (isDoc) {
        await onUploadFile(file)
      } else {
        antdMessage.warning(`不支持的文件类型：${file.name}`)
      }
    }
  }

  const onDragEnter = (e: DragEvent) => {
    if (e.dataTransfer.types?.includes('Files')) {
      e.preventDefault()
      dragCounter.current += 1
      setDragOver(true)
    }
  }
  const onDragOver = (e: DragEvent) => {
    if (e.dataTransfer.types?.includes('Files')) e.preventDefault()
  }
  const onDragLeave = (e: DragEvent) => {
    if (e.dataTransfer.types?.includes('Files')) {
      dragCounter.current -= 1
      if (dragCounter.current <= 0) {
        dragCounter.current = 0
        setDragOver(false)
      }
    }
  }
  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    dragCounter.current = 0
    setDragOver(false)
    if (e.dataTransfer.files?.length) {
      void handleDroppedFiles(e.dataTransfer.files)
    }
  }

  const onSend = async (overrideText?: string) => {
    const text = (overrideText ?? input).trim()
    if (!text || sending) return
    setSending(true)
    setInput('')
    const imgs = pendingImages
    const files = pendingFiles
    setPendingImages([])
    setPendingFiles([])

    // 先插入用户消息 + 占位的 AI 消息
    const now = new Date().toISOString()
    const userMsg: UiMessage = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: text,
      images: imgs.map((i) => i.url),
      attachments: files.map((f) => ({ file_name: f.file_name })),
      createdAt: now,
    }
    const aiMsg: UiMessage = {
      id: `a-${Date.now()}`,
      role: 'assistant',
      content: '',
      toolCalls: [],
      toolRuns: [],
      streaming: true,
    }
    setMessages((prev) => [...prev, userMsg, aiMsg])

    let convId = activeId
    // 新发送前断开可能存在的续传订阅，避免与本次发送流重复渲染
    resumeAbortRef.current?.abort()
    resumeAbortRef.current = null
    sendAbortRef.current?.abort()
    const controller = new AbortController()
    sendAbortRef.current = controller
    await streamChat(
      {
        conversationId: convId,
        message: text,
        skillId: activeSkillId,
        greeting: pendingGreetingRef.current,
        imageKeys: imgs.map((i) => i.key),
        attachments: files,
        enableWebSearch: webSearch,
      },
      {
        onMeta: (d) => {
          convId = d.conversation_id
          pendingGreetingRef.current = null // 开场白只在首轮带一次
          if (!activeId) setActiveId(d.conversation_id)
          setMessages((prev) =>
            prev.map((m) =>
              m.id === aiMsg.id || m.id === userMsg.id
                ? { ...m, conversationId: d.conversation_id }
                : m,
            ),
          )
        },
        onToken: (t) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === aiMsg.id ? { ...m, content: m.content + t } : m,
            ),
          )
        },
        onToolStart: (tc) => startToolRun(aiMsg.id, tc),
        onToolResult: (tc) => finishToolRun(aiMsg.id, tc),
        onCitation: (cites) => {
          setMessages((prev) =>
            prev.map((m) => (m.id === aiMsg.id ? { ...m, citations: cites } : m)),
          )
        },
        onDone: (d) => {
          settleRunningToolRuns(aiMsg.id, 'success')
          setMessages((prev) =>
            prev.map((m) =>
              m.id === aiMsg.id
                ? {
                    ...m,
                    streaming: false,
                    id: d.message_id ?? m.id,
                    conversationId: d.conversation_id,
                    createdAt: m.createdAt ?? new Date().toISOString(),
                  }
                : m,
            ),
          )
          setSending(false)
          loadConversations()
        },
        onError: (msg) => {
          settleRunningToolRuns(aiMsg.id, 'error')
          setMessages((prev) =>
            prev.map((m) =>
              m.id === aiMsg.id
                ? { ...m, content: `⚠️ ${msg}`, streaming: false }
                : m,
            ),
          )
          setSending(false)
        },
      },
      controller.signal,
    ).catch((e: unknown) => {
      // 中断（切页面/重发）属正常：后台生成不受影响，静默吞掉
      if ((e as Error)?.name !== 'AbortError') throw e
    })
  }

  // 快捷提问/建议词：填进输入框并聚焦（不直接发送），
  // 因为很多快捷语是「待补全的开头」（如「翻译这段话」），直接发会漏掉正文。
  const fillInput = (text: string) => {
    setInput(text)
    setTimeout(() => inputRef.current?.focus(), 0)
  }

  // 划词追问：选中 AI 回答片段 → 把引用填进输入框待补充（追问留空待问，解释预填请求）
  const onQuoteAsk = (quote: string, mode: 'ask' | 'explain') => {
    const clip = quote.length > 200 ? quote.slice(0, 200) + '…' : quote
    const prefix =
      mode === 'explain'
        ? `请解释这句：「${clip}」\n`
        : `关于「${clip}」，`
    setInput((prev) => (prev ? prev + '\n' + prefix : prefix))
    setTimeout(() => inputRef.current?.focus(), 0)
  }

  const SUGGESTIONS = [
    '帮我总结一下知识库里的内容',
    '我最近都聊过些什么？',
    '联网查一下今天有什么科技新闻',
    '根据我的记忆，给我一些建议',
  ]

  const sidebar = (
    <div className="chat-sidebar">
      <div style={{ padding: 16 }}>
        <Button
          type="primary"
          block
          size="large"
          icon={<PlusOutlined />}
          onClick={newConversation}
          className="chat-new-btn"
        >
          新对话
        </Button>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: '0 10px 10px' }}>
        {conversations.length === 0 && (
          <div className="chat-conv-empty">还没有对话，点上方开始</div>
        )}
        {convGroups.map((group) => {
          const collapsed = collapsedGroups.has(group.key)
          return (
            <div key={group.key} style={{ marginBottom: 6 }}>
              <div onClick={() => toggleGroup(group.key)} className="chat-group-title">
                {collapsed ? (
                  <RightOutlined style={{ fontSize: 10 }} />
                ) : (
                  <DownOutlined style={{ fontSize: 10 }} />
                )}
                <span>{group.label}</span>
                <span style={{ color: '#CBD2DC', fontWeight: 400 }}>
                  {group.items.length}
                </span>
              </div>
              {!collapsed &&
                group.items.map((c) => (
                  <div
                    key={c.id}
                    onClick={() => openConversation(c.id)}
                    className={`chat-conv-item${c.id === activeId ? ' active' : ''}`}
                  >
                    <span className="chat-conv-title">{c.title}</span>
                    <Popconfirm
                      title="删除该会话？"
                      onConfirm={(e) => {
                        e?.stopPropagation()
                        onDeleteConversation(c.id)
                      }}
                      onCancel={(e) => e?.stopPropagation()}
                    >
                      <DeleteOutlined
                        onClick={(e) => e.stopPropagation()}
                        className="chat-conv-del"
                      />
                    </Popconfirm>
                  </div>
                ))}
            </div>
          )
        })}
      </div>
    </div>
  )

  return (
    <div
      className="chat-layout"
      style={{
        display: 'flex',
        height: '100%',
        gap: 16,
      }}
    >
      {/* 会话列表：桌面常驻；移动端收进抽屉 */}
      {isMobile ? (
        <Drawer
          placement="left"
          open={convDrawerOpen}
          onClose={() => setConvDrawerOpen(false)}
          width={280}
          closable={false}
          styles={{ body: { padding: 0, display: 'flex', flexDirection: 'column' } }}
        >
          {sidebar}
        </Drawer>
      ) : (
        sidebar
      )}

      {/* 对话主区 */}
      <div
        className="chat-main"
        style={{ position: 'relative' }}
        onDragEnter={onDragEnter}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
      >
        {dragOver && (
          <div className="chat-drop-overlay">
            <div className="chat-drop-inner">
              <PaperClipOutlined style={{ fontSize: 34 }} />
              <div style={{ fontSize: 17, fontWeight: 600, marginTop: 10 }}>
                松开以添加到本次对话
              </div>
              <div style={{ fontSize: 13, color: '#667085', marginTop: 4 }}>
                支持图片与文档（PDF / Word / Markdown / TXT / HTML）
              </div>
            </div>
          </div>
        )}
        {/* 分享当前会话（桌面端右上角悬浮；手机端移到顶栏，避免挡对话） */}
        {!isMobile && activeId && messages.length > 0 && (
          <Tooltip title="分享这段对话">
            <Button
              className="chat-share-btn"
              icon={<ShareAltOutlined />}
              onClick={() => setShareOpen(true)}
            >
              分享
            </Button>
          </Tooltip>
        )}
        <div ref={scrollRef} className="chat-scroll" style={{ flex: 1, overflowY: 'auto', padding: '28px 0' }}>
          {messages.length === 0 ? (
            <div className="chat-empty">
              <div className="chat-empty-orb">💬</div>
              <div className="chat-empty-title">开始一段对话</div>
              <div className="chat-empty-sub">
                我会按需查知识库、调记忆或联网搜索
              </div>
              <div className="chat-suggestions">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    className="chat-suggestion"
                    onClick={() => fillInput(s)}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="chat-fluid" style={{ padding: '0 24px' }}>
              {messages.map((m) => (
                <div
                  key={m.id}
                  ref={(el) => {
                    msgRefs.current[m.id] = el
                  }}
                  style={{
                    borderRadius: 12,
                    transition: 'background 0.4s',
                    background: highlightId === m.id ? '#FFF7E6' : 'transparent',
                  }}
                >
                  <MessageItem msg={m} onRegenerate={onRegenerate} avatars={avatars} />
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 输入区 */}
        <div
          className={`chat-input-bar${
            isMobile && playerVisible ? ' chat-input-bar--player' : ''
          }`}
        >
          <div className="chat-fluid" style={{ padding: '0 24px' }}>
            {/* 技能选择器 + 快捷开场提问 */}
            <div className="chat-skill-bar">
              <Popover
                trigger="click"
                placement="topLeft"
                content={
                  <div className="chat-skill-menu">
                    <div
                      className={`chat-skill-opt${!activeSkillId ? ' active' : ''}`}
                      onClick={() => setActiveSkillId(null)}
                    >
                      <span>🚫 不挂载技能</span>
                    </div>
                    {visibleSkills.length === 0 && (
                      <div className="chat-skill-empty">
                        还没有可用技能，去「技能」页创建或开启显示
                      </div>
                    )}
                    {visibleSkills.map((s) => (
                      <div
                        key={s.id}
                        className={`chat-skill-opt${
                          activeSkillId === s.id ? ' active' : ''
                        }`}
                        onClick={() => setActiveSkillId(s.id)}
                      >
                        <span>
                          {s.icon} {s.name}
                        </span>
                      </div>
                    ))}
                  </div>
                }
              >
                <button
                  className={`chat-skill-trigger${activeSkill ? ' on' : ''}`}
                >
                  <ThunderboltOutlined />
                  {activeSkill ? `${activeSkill.icon} ${activeSkill.name}` : '技能'}
                </button>
              </Popover>
              {activeSkill && (
                <button
                  className="chat-skill-clear"
                  onClick={() => setActiveSkillId(null)}
                  title="卸载技能"
                >
                  <CloseOutlined />
                </button>
              )}
              {/* 快捷开场提问：填进输入框待补充，不直接发送 */}
              {activeSkill?.config?.quick_prompts?.map((qp, i) => (
                <button
                  key={i}
                  className="chat-quick-prompt"
                  disabled={sending}
                  onClick={() => fillInput(qp)}
                  title="填入输入框，可补充后发送"
                >
                  {qp}
                </button>
              ))}
            </div>
            {pendingImages.length > 0 && (
              <Space wrap style={{ marginBottom: 10 }}>
                {pendingImages.map((img, i) => (
                  <div key={i} style={{ position: 'relative' }}>
                    <AuthenticatedImage
                      src={img.url}
                      alt=""
                      style={{ width: 64, height: 64, borderRadius: 10, objectFit: 'cover' }}
                    />
                    <DeleteOutlined
                      onClick={() => setPendingImages((prev) => prev.filter((_, idx) => idx !== i))}
                      style={{
                        position: 'absolute',
                        top: -6,
                        right: -6,
                        background: '#fff',
                        borderRadius: '50%',
                        color: '#FF5D34',
                        fontSize: 15,
                      }}
                    />
                  </div>
                ))}
              </Space>
            )}
            {pendingFiles.length > 0 && (
              <Space wrap style={{ marginBottom: 10 }}>
                {pendingFiles.map((f, i) => (
                  <div key={i} className="chat-file-chip">
                    <FileTextOutlined style={{ color: '#155EEF' }} />
                    <span className="chat-file-chip__name" title={f.file_name}>
                      {f.file_name}
                    </span>
                    <CloseOutlined
                      className="chat-file-chip__del"
                      onClick={() =>
                        setPendingFiles((prev) => prev.filter((_, idx) => idx !== i))
                      }
                    />
                  </div>
                ))}
              </Space>
            )}
            <div className="chat-input-box">
              {isMobile ? (
                // 手机端：单行紧凑 —— [＋ 工具] [输入框] [发送箭头]
                <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8 }}>
                  <Popover
                    trigger="click"
                    placement="topLeft"
                    content={
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 160 }}>
                        <Upload accept="image/*" showUploadList={false} beforeUpload={onUploadImage as never}>
                          <Button type="text" block style={{ textAlign: 'left' }} icon={<PictureOutlined />}>
                            图片
                          </Button>
                        </Upload>
                        <Upload
                          accept=".pdf,.docx,.md,.markdown,.txt,.html,.htm"
                          showUploadList={false}
                          beforeUpload={onUploadFile as never}
                        >
                          <Button type="text" block style={{ textAlign: 'left' }} icon={<PaperClipOutlined />}>
                            文档
                          </Button>
                        </Upload>
                        <div
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            padding: '4px 8px',
                          }}
                        >
                          <span>
                            <GlobalOutlined
                              style={{ marginRight: 6, color: webSearch ? '#155EEF' : '#98A2B3' }}
                            />
                            联网搜索
                          </span>
                          <Switch size="small" checked={webSearch} onChange={setWebSearch} />
                        </div>
                      </div>
                    }
                  >
                    <Button
                      type="text"
                      shape="circle"
                      icon={<PlusOutlined style={{ fontSize: 18 }} />}
                      style={{ flexShrink: 0, color: webSearch ? '#155EEF' : undefined }}
                    />
                  </Popover>
                  <VoiceInputButton
                    size={18}
                    onResult={(t) => setInput((prev) => (prev ? prev + ' ' + t : t))}
                  />
                  <Input.TextArea
                    ref={inputRef as never}
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onPressEnter={(e) => {
                      if (!e.shiftKey) {
                        e.preventDefault()
                        onSend()
                      }
                    }}
                    placeholder="输入消息…"
                    variant="borderless"
                    autoSize={{ minRows: 1, maxRows: 5 }}
                    style={{ fontSize: 16, padding: '4px 0', resize: 'none', flex: 1 }}
                  />
                  <Button
                    type="primary"
                    shape="circle"
                    icon={<ArrowUpOutlined />}
                    loading={sending}
                    disabled={!input.trim()}
                    onClick={() => onSend()}
                    style={{ flexShrink: 0 }}
                  />
                </div>
              ) : (
                <>
                  <Input.TextArea
                    ref={inputRef as never}
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onPressEnter={(e) => {
                      if (!e.shiftKey) {
                        e.preventDefault()
                        onSend()
                      }
                    }}
                    placeholder="输入消息，Enter 发送，Shift+Enter 换行"
                    variant="borderless"
                    autoSize={{ minRows: 2, maxRows: 8 }}
                    style={{ fontSize: 16, padding: 0, resize: 'none' }}
                  />
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      marginTop: 10,
                    }}
                  >
                    <Space size="large" align="center">
                      <Upload accept="image/*" showUploadList={false} beforeUpload={onUploadImage as never}>
                        <Tooltip title="上传图片">
                          <Button type="text" icon={<PictureOutlined style={{ fontSize: 19 }} />} />
                        </Tooltip>
                      </Upload>
                      <Upload
                        accept=".pdf,.docx,.md,.markdown,.txt,.html,.htm"
                        showUploadList={false}
                        beforeUpload={onUploadFile as never}
                      >
                        <Tooltip title="上传文档（仅本次对话，不进知识库）">
                          <Button type="text" icon={<PaperClipOutlined style={{ fontSize: 19 }} />} />
                        </Tooltip>
                      </Upload>
                      <Tooltip title="联网搜索">
                        <span
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 6,
                            height: 32,
                          }}
                        >
                          <GlobalOutlined
                            style={{ fontSize: 18, color: webSearch ? '#155EEF' : '#98A2B3' }}
                          />
                          <Switch size="small" checked={webSearch} onChange={setWebSearch} />
                        </span>
                      </Tooltip>
                      <VoiceInputButton
                        onResult={(t) => setInput((prev) => (prev ? prev + ' ' + t : t))}
                      />
                    </Space>
                    <Button
                      type="primary"
                      size="large"
                      icon={<SendOutlined />}
                      loading={sending}
                      onClick={() => onSend()}
                      className="chat-send-btn"
                    >
                      发送
                    </Button>
                  </div>
                </>
              )}
            </div>
            {!isMobile && (
              <div style={{ textAlign: 'center', fontSize: 12, color: '#98A2B3', marginTop: 8 }}>
                内容由 AI 生成，请注意甄别
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 划词追问：选中 AI 回答片段浮出「追问/解释」 */}
      <SelectionPopover onAsk={onQuoteAsk} />

      {/* 分享对话弹窗 */}
      <ShareModal
        open={shareOpen}
        conversationId={activeId}
        onClose={() => setShareOpen(false)}
      />
    </div>
  )
}
