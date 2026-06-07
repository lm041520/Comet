import { useEffect, useRef, useState, type DragEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Button,
  Input,
  Popconfirm,
  Space,
  Switch,
  Tooltip,
  Upload,
  message as antdMessage,
} from 'antd'
import {
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
} from '@ant-design/icons'
import {
  chatApi,
  streamChat,
  regenerateMessage,
  type Conversation,
  type ChatMessage,
} from '@/api/chat'
import { agentConfigApi } from '@/api/agentConfig'
import { favoriteApi } from '@/api/favorites'
import { AuthenticatedImage } from '@/components/AuthenticatedImage'
import MessageItem from './chat/MessageItem'
import type { UiMessage } from './chat/types'
import { groupConversationsByDate } from './chat/groupByDate'

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
  const [pendingImages, setPendingImages] = useState<{ key: string; url: string }[]>([])
  const [pendingFiles, setPendingFiles] = useState<
    { file_name: string; text: string }[]
  >([])
  const [dragOver, setDragOver] = useState(false)
  const dragCounter = useRef(0)
  const [highlightId, setHighlightId] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const msgRefs = useRef<Record<string, HTMLDivElement | null>>({})
  const groupsInited = useRef(false)

  const convGroups = groupConversationsByDate(conversations)

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
      setConversations(data)
    } catch (e) {
      antdMessage.error((e as Error).message)
    }
  }

  useEffect(() => {
    loadConversations()
  }, [])

  // 读取 Agent 配置：联网搜索开关默认跟随用户在 Agent 配置里的设置
  useEffect(() => {
    agentConfigApi
      .get()
      .then(({ data }) => setWebSearch(data.enable_web_search))
      .catch(() => {
        // 取配置失败则保持默认关闭，不影响对话
      })
  }, [])

  // 收藏深链：?conversation=&message= 打开会话并定位消息
  useEffect(() => {
    const conv = params.get('conversation')
    const msg = params.get('message')
    if (conv) {
      openConversation(conv, msg ?? undefined)
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
          attachments: m.meta_data?.attachments?.map((a) => ({
            file_name: a.file_name,
          })),
          conversationId: id,
          favId: favByMsg[m.id] ?? null,
          feedback: m.feedback ?? null,
          createdAt: m.created_at,
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
    } catch (e) {
      antdMessage.error((e as Error).message)
    }
  }

  const newConversation = () => {
    setActiveId(undefined)
    setMessages([])
  }

  // 重新生成某条 AI 回复：替换该条消息内容，重新流式
  const onRegenerate = async (target: UiMessage) => {
    if (sending) return
    setSending(true)
    setMessages((prev) =>
      prev.map((m) =>
        m.id === target.id
          ? { ...m, content: '', toolCalls: [], citations: undefined, streaming: true, feedback: null }
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
      onToolCall: (tc) => {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === aiId ? { ...m, toolCalls: [...(m.toolCalls ?? []), tc] } : m,
          ),
        )
      },
      onCitation: (cites) => {
        setMessages((prev) =>
          prev.map((m) => (m.id === aiId ? { ...m, citations: cites } : m)),
        )
      },
      onDone: (d) => {
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
    return false // 阻止 antd 默认上传
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
    return false // 阻止 antd 默认上传
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

  const onSend = async () => {
    const text = input.trim()
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
      streaming: true,
    }
    setMessages((prev) => [...prev, userMsg, aiMsg])

    let convId = activeId
    await streamChat(
      {
        conversationId: convId,
        message: text,
        imageKeys: imgs.map((i) => i.key),
        attachments: files,
        enableWebSearch: webSearch,
      },
      {
        onMeta: (d) => {
          convId = d.conversation_id
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
        onToolCall: (tc) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === aiMsg.id
                ? { ...m, toolCalls: [...(m.toolCalls ?? []), tc] }
                : m,
            ),
          )
        },
        onCitation: (cites) => {
          setMessages((prev) =>
            prev.map((m) => (m.id === aiMsg.id ? { ...m, citations: cites } : m)),
          )
        },
        onDone: (d) => {
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
    )
  }

  const SUGGESTIONS = [
    '帮我总结一下知识库里的内容',
    '我最近都聊过些什么？',
    '联网查一下今天有什么科技新闻',
    '根据我的记忆，给我一些建议',
  ]

  return (
    <div
      className="chat-layout"
      style={{
        display: 'flex',
        height: '100%',
        gap: 16,
      }}
    >
      {/* 会话列表 */}
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
                <div
                  onClick={() => toggleGroup(group.key)}
                  className="chat-group-title"
                >
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
        <div ref={scrollRef} style={{ flex: 1, overflowY: 'auto', padding: '28px 0' }}>
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
                    onClick={() => setInput(s)}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="fluid-narrow" style={{ padding: '0 24px' }}>
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
                  <MessageItem msg={m} onRegenerate={onRegenerate} />
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 输入区 */}
        <div className="chat-input-bar">
          <div className="fluid-narrow" style={{ padding: '0 24px' }}>
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
              <Input.TextArea
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
                <Space size="large">
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
                    <Space size={6}>
                      <GlobalOutlined
                        style={{ fontSize: 18, color: webSearch ? '#155EEF' : '#98A2B3' }}
                      />
                      <Switch size="small" checked={webSearch} onChange={setWebSearch} />
                    </Space>
                  </Tooltip>
                </Space>
                <Button
                  type="primary"
                  size="large"
                  icon={<SendOutlined />}
                  loading={sending}
                  onClick={onSend}
                >
                  发送
                </Button>
              </div>
            </div>
            <div style={{ textAlign: 'center', fontSize: 12, color: '#98A2B3', marginTop: 8 }}>
              内容由 AI 生成，请注意甄别
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
