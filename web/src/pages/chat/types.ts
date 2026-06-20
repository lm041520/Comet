import type { Citation, ToolCall, ToolRun } from '@/api/chat'

// 前端消息模型（含流式中的临时状态）
export interface UiMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  toolCalls?: ToolCall[]
  toolRuns?: ToolRun[]
  images?: string[] // 图片 url（用户消息）
  attachments?: { file_name: string }[] // 对话临时文档附件（仅显示文件名）
  streaming?: boolean
  conversationId?: string // 所属会话（收藏深链用）
  favId?: string | null // 已收藏时的收藏记录 id（高亮+取消用）
  feedback?: 'up' | 'down' | null // 当前用户对该 AI 消息的反馈
  createdAt?: string // 消息时间（ISO 字符串）
  fromHistory?: boolean // 来自历史加载（非本次实时生成）→ 真人模式多气泡不重放动画，直接全显
}

// 对话头像上下文：是否显示 + AI（当前角色）头像 + 用户头像
export interface ChatAvatars {
  show: boolean
  personaName?: string
  personaAvatarUrl?: string | null // AI 头像（当前角色）；空则 AI 侧不显示
  userAvatarUrl?: string | null // 用户头像；空则用户侧不显示
  humanMode?: boolean // 全局真人模式：AI 回复走「正在输入…→逐条气泡」，不显示助手过程条
}

// 格式化消息时间：今天显示 HH:mm，否则显示 月-日 HH:mm
export function formatMsgTime(iso?: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const hh = `${d.getHours()}`.padStart(2, '0')
  const mm = `${d.getMinutes()}`.padStart(2, '0')
  const now = new Date()
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  if (sameDay) return `${hh}:${mm}`
  return `${d.getMonth() + 1}-${d.getDate()} ${hh}:${mm}`
}

export const TOOL_META: Record<string, { icon: string; label: string }> = {
  knowledge_search: { icon: '🔍', label: '知识库' },
  memory_search: { icon: '🧠', label: '记忆' },
  web_search: { icon: '🌐', label: '联网' },
}

// 真人模式多气泡分隔符：模型在断句处单独输出 [[next]]，前端据此把一条回复拆成多个气泡。
export const BUBBLE_SEP_RE = /\s*\[\[next\]\]\s*/
const MAX_BUBBLES = 5

// 按分隔符把内容拆成多个气泡文本：过滤空段；超过上限则把多余的并入最后一条。
export function splitBubbles(content: string): string[] {
  const raw = (content || '').split(BUBBLE_SEP_RE).map((s) => s.trim()).filter(Boolean)
  if (raw.length <= MAX_BUBBLES) return raw
  const head = raw.slice(0, MAX_BUBBLES - 1)
  const tail = raw.slice(MAX_BUBBLES - 1).join('\n')
  return [...head, tail]
}

// 是否为多气泡内容（含分隔符）。复制时把分隔符还原成换行。
export function hasBubbleSep(content: string): boolean {
  return /\[\[next\]\]/.test(content || '')
}


// 解析工具调用标记的展示信息。
// 内置工具走 TOOL_META；MCP 工具名形如 `{server}__{tool}`，拆成「服务·工具」友好展示。
// label：完整名（hover/详情用）；short：精简名（chip 紧凑展示用，MCP 只留工具名）。
export function resolveToolMeta(toolName: string): {
  icon: string
  label: string
  short: string
} {
  const builtin = TOOL_META[toolName]
  if (builtin) return { ...builtin, short: builtin.label }
  if (toolName.includes('__')) {
    const idx = toolName.indexOf('__')
    const server = toolName.slice(0, idx)
    const tool = toolName.slice(idx + 2)
    return { icon: '🧩', label: `MCP · ${server} / ${tool}`, short: tool }
  }
  return { icon: '🛠️', label: toolName, short: toolName }
}
