import client from './client'

interface Wrapped<T> {
  code: number
  message: string
  data: T
}

export interface Conversation {
  id: string
  title: string
  created_at: string
  updated_at: string
  is_group?: boolean
  member_persona_ids?: string[]
  enable_tools?: boolean
}

export interface Citation {
  source_id: string
  source_type: string | null
  doc_name: string | null
  score: number | null
}

export interface ToolCall {
  tool: string
  query: string
}

export type ToolRunStatus = 'running' | 'success' | 'error'

export interface ToolRunStats {
  hit_count?: number
  doc_count?: number
  entity_count?: number
  relation_count?: number
  web_count?: number
  provider?: string
  [k: string]: unknown
}

export interface ToolRun extends ToolCall {
  id: string
  status: ToolRunStatus
  result?: string
  stats?: ToolRunStats
  latencyMs?: number
}

export interface ChatAttachment {
  file_name: string
  text: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  images?: string[]
  meta_data: {
    citations?: Citation[]
    tool_calls?: ToolCall[]
    attachments?: { file_name: string; text?: string }[]
    image_keys?: string[]
  } | null
  feedback?: 'up' | 'down' | null
  created_at: string
}

export interface SendOptions {
  conversationId?: string
  message: string
  skillId?: string | null
  greeting?: string | null
  imageKeys?: string[]
  attachments?: ChatAttachment[]
  enableKnowledge?: boolean
  enableMemory?: boolean
  enableWebSearch?: boolean
}

// SSE 事件回调
export interface StreamHandlers {
  onMeta?: (d: { conversation_id: string; title: string }) => void
  onToken?: (text: string) => void
  onToolStart?: (d: ToolCall) => void
  onToolResult?: (d: ToolCall & {
    status?: ToolRunStatus
    text?: string
    stats?: ToolRunStats
    latency_ms?: number
  }) => void
  onToolCall?: (d: ToolCall) => void
  onCitation?: (citations: Citation[]) => void
  onDone?: (d: { conversation_id: string; message_id?: string }) => void
  onError?: (message: string) => void
  // 断线重连续传：补推已生成内容（content 为累积全文，需整体替换当前流式气泡）
  onResume?: (d: {
    content: string
    citations?: Citation[]
    tool_calls?: ToolCall[]
  }) => void
  // 没有进行中的生成（已结束/无）：前端据此结束续传、去重拉历史
  onIdle?: () => void
}

export const chatApi = {
  listConversations() {
    return client.get<unknown, Wrapped<Conversation[]>>('/conversations')
  },
  createConversation(title = '新对话') {
    return client.post<unknown, Wrapped<Conversation>>('/conversations', { title })
  },
  renameConversation(id: string, title: string) {
    return client.put<unknown, Wrapped<Conversation>>(`/conversations/${id}`, { title })
  },
  deleteConversation(id: string) {
    return client.delete<unknown, Wrapped<null>>(`/conversations/${id}`)
  },
  listMessages(id: string) {
    return client.get<unknown, Wrapped<ChatMessage[]>>(`/conversations/${id}/messages`)
  },
  uploadImage(file: File) {
    const form = new FormData()
    form.append('file', file)
    return client.post<unknown, Wrapped<{ file_key: string; url: string }>>(
      '/chat/upload-image',
      form,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    )
  },
  uploadFile(file: File) {
    const form = new FormData()
    form.append('file', file)
    return client.post<
      unknown,
      Wrapped<{ file_name: string; text: string; chars: number; truncated: boolean }>
    >('/chat/upload-file', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  // 语音转文字（路 B 云端 ASR）：上传音频，返回识别文本。未配 ASR 模型时后端报错降级
  transcribe(blob: Blob) {
    const form = new FormData()
    const ext = blob.type.includes('wav') ? 'wav' : blob.type.includes('mp4') ? 'm4a' : 'webm'
    form.append('file', blob, `voice.${ext}`)
    return client.post<unknown, Wrapped<{ text: string }>>('/chat/transcribe', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  setFeedback(messageId: string, rating: 'up' | 'down') {
    return client.post<unknown, Wrapped<{ id: string; rating: string }>>(
      `/chat/messages/${messageId}/feedback`,
      { rating },
    )
  },
  removeFeedback(messageId: string) {
    return client.delete<unknown, Wrapped<null>>(`/chat/messages/${messageId}/feedback`)
  },
}

// ── 群聊（多角色卡） ──

export interface GroupMember {
  id: string
  name: string
  avatar_url: string | null
  system_prompt?: string
}

export interface GroupChatMessage extends ChatMessage {
  sender_persona_id?: string | null
  sender_name?: string | null
}

export interface GroupStreamHandlers {
  onMeta?: (d: { conversation_id: string; title: string }) => void
  onSpeakerStart?: (d: {
    persona_id: string
    name: string
    avatar_url: string | null
  }) => void
  onToken?: (text: string) => void
  onToolStart?: (d: { tool: string; query: string }) => void
  onToolResult?: (d: {
    tool: string
    query: string
    status?: string
    text?: string
    stats?: Record<string, unknown>
    latency_ms?: number
  }) => void
  onSpeakerEnd?: (d: { persona_id: string; message_id: string }) => void
  onDone?: (d: { conversation_id: string }) => void
  onError?: (message: string) => void
}

export const groupApi = {
  createGroup(memberPersonaIds: string[], title?: string, enableTools = false) {
    return client.post<unknown, Wrapped<Conversation>>('/groups', {
      member_persona_ids: memberPersonaIds,
      title: title ?? null,
      enable_tools: enableTools,
    })
  },
  listMembers(convId: string) {
    return client.get<unknown, Wrapped<GroupMember[]>>(`/groups/${convId}/members`)
  },
  clearMessages(convId: string) {
    return client.delete<unknown, Wrapped<null>>(`/groups/${convId}/messages`)
  },
  // ── 多人实时群聊 ──
  listGroups() {
    return client.get<unknown, Wrapped<GroupConversation[]>>('/groups')
  },
  listGroupMessages(convId: string) {
    return client.get<unknown, Wrapped<GroupChatMessage[]>>(`/groups/${convId}/messages`)
  },
  getInvite(convId: string) {
    return client.post<unknown, Wrapped<{ join_code: string }>>(
      `/groups/${convId}/invite`,
    )
  },
  resetInvite(convId: string) {
    return client.post<unknown, Wrapped<{ join_code: string }>>(
      `/groups/${convId}/invite/reset`,
    )
  },
  setTools(convId: string, enabled: boolean) {
    return client.patch<unknown, Wrapped<{ enable_tools: boolean }>>(
      `/groups/${convId}/tools`,
      { enabled },
    )
  },
  join(code: string, nickname?: string) {
    return client.post<unknown, Wrapped<Conversation>>('/groups/join', {
      code,
      nickname: nickname ?? null,
    })
  },
  leave(convId: string) {
    return client.post<unknown, Wrapped<null>>(`/groups/${convId}/leave`)
  },
  listHumans(convId: string) {
    return client.get<unknown, Wrapped<GroupHuman[]>>(`/groups/${convId}/humans`)
  },
  say(convId: string, message: string, imageKeys?: string[]) {
    return client.post<unknown, Wrapped<{ message_id: string }>>(
      `/groups/${convId}/say`,
      { message, image_keys: imageKeys ?? [] },
    )
  },
}

export interface GroupConversation extends Conversation {
  is_owner?: boolean
  // 群头像宫格成员（真人 + AI 角色卡，最多 4 个），来自后端组合
  avatar_members?: { name: string; avatar_url?: string | null }[]
}

export interface GroupHuman {
  user_id: string
  nickname: string
  role: 'owner' | 'member'
  is_me: boolean
  avatar_url?: string | null
  online?: boolean
}

// 多人实时群聊 SSE 订阅事件
export interface GroupRealtimeHandlers {
  onReady?: (d: { conversation_id: string }) => void
  onPresence?: (d: {
    type: 'join' | 'leave' | 'online' | 'offline'
    nickname?: string
    user_id?: string
  }) => void
  onThinking?: () => void
  onHumanMessage?: (d: {
    message_id: string
    user_id: string
    nickname: string
    content: string
    image_keys?: string[]
    created_at?: string
  }) => void
  onSpeakerStart?: (d: {
    persona_id: string
    name: string
    avatar_url: string | null
  }) => void
  onToken?: (d: { persona_id?: string; text: string }) => void
  onToolStart?: (d: { tool: string; query: string }) => void
  onToolResult?: (d: {
    tool: string
    query: string
    status?: string
    stats?: Record<string, unknown>
    latency_ms?: number
  }) => void
  onSpeakerEnd?: (d: { persona_id: string; message_id: string }) => void
  onDone?: (d: { conversation_id: string }) => void
  onError?: (message: string) => void
}

// 订阅群聊实时事件（GET SSE，用 fetch + ReadableStream；signal 控制断开）
export async function subscribeGroupEvents(
  convId: string,
  handlers: GroupRealtimeHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const token = localStorage.getItem('access_token')
  const resp = await fetch(`/api/groups/${convId}/events`, {
    method: 'GET',
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    signal,
  })
  if (!resp.ok || !resp.body) {
    handlers.onError?.(`订阅失败（HTTP ${resp.status}）`)
    return
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() ?? ''
    for (const block of blocks) {
      const lines = block.split('\n')
      let event = 'message'
      let data = ''
      for (const line of lines) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trim()
      }
      if (!data) continue
      let payload: Record<string, unknown> = {}
      try {
        payload = JSON.parse(data)
      } catch {
        continue
      }
      switch (event) {
        case 'ready':
          handlers.onReady?.(payload as never)
          break
        case 'presence':
          handlers.onPresence?.(payload as never)
          break
        case 'thinking':
          handlers.onThinking?.()
          break
        case 'human_message':
          handlers.onHumanMessage?.(payload as never)
          break
        case 'speaker_start':
          handlers.onSpeakerStart?.(payload as never)
          break
        case 'token':
          handlers.onToken?.(payload as never)
          break
        case 'tool_start':
          handlers.onToolStart?.(payload as never)
          break
        case 'tool_result':
          handlers.onToolResult?.(payload as never)
          break
        case 'speaker_end':
          handlers.onSpeakerEnd?.(payload as never)
          break
        case 'done':
          handlers.onDone?.(payload as never)
          break
        case 'error':
          handlers.onError?.((payload.message as string) ?? '群聊出错')
          break
      }
    }
  }
}

// 群聊流式：解析 speaker_start / token / speaker_end 等事件
export async function streamGroupChat(
  conversationId: string,
  message: string,
  handlers: GroupStreamHandlers,
  signal?: AbortSignal,
  imageKeys?: string[],
): Promise<void> {
  const token = localStorage.getItem('access_token')
  const resp = await fetch('/api/groups/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      conversation_id: conversationId,
      message,
      image_keys: imageKeys ?? [],
    }),
    signal,
  })
  if (!resp.ok || !resp.body) {
    handlers.onError?.(`请求失败（HTTP ${resp.status}）`)
    return
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() ?? ''
    for (const block of blocks) {
      const lines = block.split('\n')
      let event = 'message'
      let data = ''
      for (const line of lines) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trim()
      }
      if (!data) continue
      let payload: Record<string, unknown> = {}
      try {
        payload = JSON.parse(data)
      } catch {
        continue
      }
      switch (event) {
        case 'meta':
          handlers.onMeta?.(payload as never)
          break
        case 'speaker_start':
          handlers.onSpeakerStart?.(payload as never)
          break
        case 'token':
          handlers.onToken?.(payload.text as string)
          break
        case 'tool_start':
          handlers.onToolStart?.(payload as never)
          break
        case 'tool_result':
          handlers.onToolResult?.(payload as never)
          break
        case 'speaker_end':
          handlers.onSpeakerEnd?.(payload as never)
          break
        case 'done':
          handlers.onDone?.(payload as never)
          break
        case 'error':
          handlers.onError?.((payload.message as string) ?? '群聊出错')
          break
      }
    }
  }
}

// SSE 流式发送：用 fetch + ReadableStream 解析 text/event-stream
export async function streamChat(
  opts: SendOptions,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  await streamSSE(
    '/api/chat/stream',
    {
      conversation_id: opts.conversationId ?? null,
      message: opts.message,
      skill_id: opts.skillId ?? null,
      greeting: opts.greeting ?? null,
      image_keys: opts.imageKeys ?? [],
      attachments: opts.attachments ?? [],
      enable_knowledge: opts.enableKnowledge ?? null,
      enable_memory: opts.enableMemory ?? null,
      enable_web_search: opts.enableWebSearch ?? null,
    },
    handlers,
    signal,
  )
}

// 重新生成某条 AI 回复（复用 SSE 解析）
export async function regenerateMessage(
  messageId: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  await streamSSE(`/api/chat/messages/${messageId}/regenerate`, {}, handlers, signal)
}

// 断线重连续传：订阅某会话「进行中的生成」（GET SSE）。
// 后端若发现没有进行中的生成会立即返回 idle 并结束。
export async function subscribeChatEvents(
  convId: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const token = localStorage.getItem('access_token')
  let resp: Response
  try {
    resp = await fetch(`/api/chat/${convId}/events`, {
      method: 'GET',
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      signal,
    })
  } catch {
    // 网络错误/主动中断：静默（前端自行处理重连）
    return
  }
  if (!resp.ok || !resp.body) return
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    let chunk: ReadableStreamReadResult<Uint8Array>
    try {
      chunk = await reader.read()
    } catch {
      break
    }
    if (chunk.done) break
    buffer += decoder.decode(chunk.value, { stream: true })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() ?? ''
    for (const block of blocks) {
      const lines = block.split('\n')
      let event = 'message'
      let data = ''
      for (const line of lines) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trim()
      }
      if (!data) continue
      let payload: Record<string, unknown> = {}
      try {
        payload = JSON.parse(data)
      } catch {
        continue
      }
      dispatchEvent(event, payload, handlers)
    }
  }
}

// 通用 SSE POST 解析
async function streamSSE(
  url: string,
  body: Record<string, unknown>,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const token = localStorage.getItem('access_token')
  const resp = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  })

  if (!resp.ok || !resp.body) {
    handlers.onError?.(`请求失败（HTTP ${resp.status}）`)
    return
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    // 按 SSE 事件分隔（空行）切分
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() ?? ''
    for (const block of blocks) {
      const lines = block.split('\n')
      let event = 'message'
      let data = ''
      for (const line of lines) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trim()
      }
      if (!data) continue
      let payload: Record<string, unknown> = {}
      try {
        payload = JSON.parse(data)
      } catch {
        continue
      }
      dispatchEvent(event, payload, handlers)
    }
  }
}

function dispatchEvent(
  event: string,
  payload: Record<string, unknown>,
  handlers: StreamHandlers,
) {
  switch (event) {
    case 'meta':
      handlers.onMeta?.(payload as never)
      break
    case 'token':
      handlers.onToken?.(payload.text as string)
      break
    case 'tool_start':
      handlers.onToolStart?.(payload as never)
      break
    case 'tool_result':
      handlers.onToolResult?.(payload as never)
      break
    case 'tool_call':
      handlers.onToolStart?.(payload as never)
      handlers.onToolCall?.(payload as never)
      break
    case 'citation':
      handlers.onCitation?.((payload.citations as Citation[]) ?? [])
      break
    case 'done':
      handlers.onDone?.(payload as never)
      break
    case 'resume':
      handlers.onResume?.(payload as never)
      break
    case 'idle':
      handlers.onIdle?.()
      break
    case 'error':
      handlers.onError?.((payload.message as string) ?? '生成失败')
      break
  }
}
