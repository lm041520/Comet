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

export interface ChatAttachment {
  file_name: string
  text: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  meta_data: {
    citations?: Citation[]
    tool_calls?: ToolCall[]
    attachments?: { file_name: string; text?: string }[]
  } | null
  feedback?: 'up' | 'down' | null
  created_at: string
}

export interface SendOptions {
  conversationId?: string
  message: string
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
  onToolCall?: (d: ToolCall) => void
  onCitation?: (citations: Citation[]) => void
  onDone?: (d: { conversation_id: string; message_id?: string }) => void
  onError?: (message: string) => void
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
    case 'tool_call':
      handlers.onToolCall?.(payload as never)
      break
    case 'citation':
      handlers.onCitation?.((payload.citations as Citation[]) ?? [])
      break
    case 'done':
      handlers.onDone?.(payload as never)
      break
    case 'error':
      handlers.onError?.((payload.message as string) ?? '生成失败')
      break
  }
}
