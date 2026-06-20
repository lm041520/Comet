import { useState } from 'react'
import { Button, Space, Tag, Tooltip, message as antdMessage } from 'antd'
import {
  CopyOutlined,
  DislikeFilled,
  DislikeOutlined,
  FileTextOutlined,
  LikeFilled,
  LikeOutlined,
  ReloadOutlined,
  StarFilled,
  StarOutlined,
} from '@ant-design/icons'
import MarkdownMessage from '@/components/MarkdownMessage'
import ChatProcess from './ChatProcess'
import HumanBubbles from './HumanBubbles'
import { favoriteApi } from '@/api/favorites'
import { chatApi } from '@/api/chat'
import { copyText } from '@/utils/clipboard'
import { AuthenticatedImage } from '@/components/AuthenticatedImage'
import type { ChatAvatars, UiMessage } from './types'
import { formatMsgTime, hasBubbleSep } from './types'

export default function MessageItem({
  msg,
  onRegenerate,
  avatars,
}: {
  msg: UiMessage
  onRegenerate?: (msg: UiMessage) => void
  avatars?: ChatAvatars
}) {
  const isUser = msg.role === 'user'
  // 本地收藏态：null 未收藏；string 已收藏（存 favorite id 供取消）
  const [favId, setFavId] = useState<string | null>(msg.favId ?? null)
  const [favLoading, setFavLoading] = useState(false)
  // 本地反馈态：up | down | null
  const [feedback, setFeedback] = useState<'up' | 'down' | null>(msg.feedback ?? null)

  const onCopy = async () => {
    // 多气泡分隔符还原成换行再复制
    const text = msg.content.replace(/\s*\[\[next\]\]\s*/g, '\n')
    const ok = await copyText(text)
    if (ok) antdMessage.success('已复制')
    else antdMessage.error('复制失败')
  }

  const onFeedback = async (rating: 'up' | 'down') => {
    try {
      if (feedback === rating) {
        // 再次点击同一个 → 取消
        await chatApi.removeFeedback(msg.id)
        setFeedback(null)
      } else {
        await chatApi.setFeedback(msg.id, rating)
        setFeedback(rating)
      }
    } catch (e) {
      antdMessage.error((e as Error).message)
    }
  }

  const onFavorite = async () => {
    if (favLoading) return
    setFavLoading(true)
    try {
      if (favId) {
        await favoriteApi.remove(favId)
        setFavId(null)
        antdMessage.success('已取消收藏')
      } else {
        const { data } = await favoriteApi.add('message', msg.id, {
          title: '对话回答',
          summary: msg.content.slice(0, 120),
          conversation_id: msg.conversationId,
        })
        setFavId(data.id)
        antdMessage.success('已收藏')
      }
    } catch (e) {
      antdMessage.error((e as Error).message)
    } finally {
      setFavLoading(false)
    }
  }

  // 头像渲染：开关开 + 对应侧有头像才显示
  const showAvatars = !!avatars?.show
  const aiAvatarUrl = avatars?.personaAvatarUrl || null
  const userAvatarUrl = avatars?.userAvatarUrl || null
  const sideAvatarUrl = isUser ? userAvatarUrl : aiAvatarUrl
  // 该侧有头像才渲染头像列；无头像则气泡占满（不占位、不强制圆形）
  const renderAvatar = () => {
    if (!showAvatars || !sideAvatarUrl) return null
    return (
      <div className="chat-avatar">
        <AuthenticatedImage
          src={sideAvatarUrl}
          alt=""
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
        />
      </div>
    )
  }
  const hasAvatar = showAvatars && !!sideAvatarUrl
  // AI 过程展示数据：toolRuns（实时）或历史 toolCalls（已存档复现）
  // 历史消息只有 toolCalls（含 status/stats/latency_ms/preview/query/tool）；运行中走 toolRuns。
  // 把它们规范成 ToolRun 数组喂给 ChatProcess 即可。
  const processRuns = (() => {
    if (isUser) return undefined
    if (msg.toolRuns && msg.toolRuns.length > 0) return msg.toolRuns
    if (msg.toolCalls && msg.toolCalls.length > 0) {
      return msg.toolCalls.map((tc, i) => {
        const ext = tc as unknown as Record<string, unknown>
        return {
          id: `${tc.tool}-hist-${i}`,
          tool: tc.tool,
          query: tc.query,
          status: ((ext.status as string) || 'success') as
            | 'running'
            | 'success'
            | 'error',
          result: typeof ext.preview === 'string' ? (ext.preview as string) : undefined,
          stats: ext.stats as Record<string, unknown> | undefined,
          latencyMs:
            typeof ext.latency_ms === 'number'
              ? (ext.latency_ms as number)
              : undefined,
        }
      })
    }
    return undefined
  })()
  const hasProcess = !isUser && (processRuns?.length ?? 0) > 0
  // AI 流式中且还没出 content 时不渲染空气泡（过程组件已经表达了"在动"）
  const shouldRenderBubble =
    isUser || (msg.content ? true : !msg.streaming && !hasProcess)
  // 全局真人模式：AI 回复走「正在输入…→逐条气泡」，不显示助手过程条（正在理解问题…）
  const humanModeActive = !!avatars?.humanMode
  const humanMode = !isUser && humanModeActive
  // 真人模式多气泡：AI 消息且内容含分隔符 → 拆成多个微信式气泡逐条展示
  const isHumanMulti = !isUser && !!msg.content && hasBubbleSep(msg.content)

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: isUser ? 'row-reverse' : 'row',
        justifyContent: 'flex-start',
        alignItems: 'flex-start',
        gap: hasAvatar ? 10 : 0,
        marginBottom: 24,
      }}
    >
      {renderAvatar()}
      <div style={{ maxWidth: '82%', minWidth: 0 }}>
        {/* AI 过程流：顶部进度线 + 状态条 + 工具 chip 行 + 可展开详情（真人模式不显示，改用「正在输入」气泡） */}
        {!isUser && !humanMode && (msg.streaming || hasProcess) && (
          <ChatProcess
            toolRuns={processRuns}
            citations={msg.citations}
            hasContent={!!msg.content}
            streaming={!!msg.streaming}
          />
        )}

        {/* 真人模式：全程走打字气泡（正在输入… → 逐条冒出），不出现助手过程条与原始流式文本 */}
        {humanMode && (msg.content || msg.streaming) && (
          <div data-ai-message="true">
            <HumanBubbles
              content={msg.content}
              streaming={msg.streaming}
              instant={!!msg.fromHistory}
            />
          </div>
        )}

        {!humanMode && shouldRenderBubble && isHumanMulti && (
          <div data-ai-message="true">
            <HumanBubbles
              content={msg.content}
              streaming={msg.streaming}
              instant={!!msg.fromHistory}
            />
          </div>
        )}

        {!humanMode && shouldRenderBubble && !isHumanMulti && (
          <div
            data-ai-message={!isUser ? 'true' : undefined}
            style={{
              background: isUser
                ? 'linear-gradient(135deg, #1d6bff 0%, #2f7bff 100%)'
                : '#fff',
              color: isUser ? '#fff' : '#1D2129',
              padding: isUser ? '12px 16px' : '14px 18px',
              borderRadius: isUser ? '16px 16px 4px 16px' : '4px 16px 16px 16px',
              border: isUser ? 'none' : '1px solid #eef0f4',
              boxShadow: isUser
                ? '0 6px 18px -6px rgba(21, 94, 239, 0.45)'
                : '0 4px 16px -10px rgba(16, 24, 40, 0.2)',
              fontSize: 16,
              lineHeight: 1.75,
            }}
          >
            {/* 用户消息图片 */}
            {isUser && msg.images && msg.images.length > 0 && (
              <Space wrap style={{ marginBottom: 8 }}>
                {msg.images.map((url, i) => (
                  <AuthenticatedImage
                    key={i}
                    src={url}
                    alt=""
                    style={{ maxWidth: 160, maxHeight: 160, borderRadius: 8 }}
                  />
                ))}
              </Space>
            )}

            {/* 用户消息附件（文档，仅显示文件名） */}
            {isUser && msg.attachments && msg.attachments.length > 0 && (
              <Space wrap style={{ marginBottom: 8 }}>
                {msg.attachments.map((a, i) => (
                  <span
                    key={i}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 6,
                      background: 'rgba(255,255,255,0.18)',
                      borderRadius: 8,
                      padding: '4px 10px',
                      fontSize: 13,
                      maxWidth: 220,
                    }}
                  >
                    <FileTextOutlined />
                    <span
                      style={{
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {a.file_name}
                    </span>
                  </span>
                ))}
              </Space>
            )}

            {isUser ? (
              <span style={{ whiteSpace: 'pre-wrap', fontSize: 16 }}>{msg.content}</span>
            ) : (
              <MarkdownMessage
                content={msg.content || (msg.streaming && !hasProcess ? '思考中…' : '')}
              />
            )}
          </div>
        )}

        {/* 用户消息复制按钮 + 时间（右对齐）；真人模式下隐藏整排 */}
        {isUser && msg.content && !humanModeActive && (
          <div
            style={{
              marginTop: 4,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'flex-end',
              gap: 4,
            }}
          >
            <Button
              size="small"
              type="text"
              icon={<CopyOutlined />}
              onClick={onCopy}
              style={{ color: '#667085', fontSize: 12 }}
            >
              复制
            </Button>
            {msg.createdAt && (
              <span style={{ fontSize: 12, color: '#B6BCC6' }}>
                {formatMsgTime(msg.createdAt)}
              </span>
            )}
          </div>
        )}

        {/* 引用来源 + 复制按钮（AI 消息）；真人模式下隐藏整排 */}
        {!isUser && !humanModeActive && (
          <div style={{ marginTop: 6 }}>
            {msg.citations && msg.citations.length > 0 && (
              <Space size={[4, 4]} wrap style={{ marginBottom: 4 }}>
                <span style={{ fontSize: 12, color: '#667085' }}>引用：</span>
                {msg.citations.map((c, i) => (
                  <Tag key={i} color="default">
                    {c.source_type === 'image' ? '🖼️' : '📄'} {c.doc_name || c.source_id}
                  </Tag>
                ))}
              </Space>
            )}
            {!msg.streaming && msg.content && (
              <>
                <Button
                  size="small"
                  type="text"
                  icon={<CopyOutlined />}
                  onClick={onCopy}
                  style={{ color: '#667085', fontSize: 12 }}
                >
                  复制
                </Button>
                <Button
                  size="small"
                  type="text"
                  icon={favId ? <StarFilled style={{ color: '#FAAD14' }} /> : <StarOutlined />}
                  onClick={onFavorite}
                  loading={favLoading}
                  style={{ color: favId ? '#FAAD14' : '#667085', fontSize: 12 }}
                >
                  {favId ? '已收藏' : '收藏'}
                </Button>
                <Tooltip title="赞">
                  <Button
                    size="small"
                    type="text"
                    icon={feedback === 'up' ? <LikeFilled style={{ color: '#155EEF' }} /> : <LikeOutlined />}
                    onClick={() => onFeedback('up')}
                    style={{ color: feedback === 'up' ? '#155EEF' : '#667085', fontSize: 12 }}
                  />
                </Tooltip>
                <Tooltip title="踩">
                  <Button
                    size="small"
                    type="text"
                    icon={feedback === 'down' ? <DislikeFilled style={{ color: '#FF5D34' }} /> : <DislikeOutlined />}
                    onClick={() => onFeedback('down')}
                    style={{ color: feedback === 'down' ? '#FF5D34' : '#667085', fontSize: 12 }}
                  />
                </Tooltip>
                {onRegenerate && (
                  <Tooltip title="重新生成">
                    <Button
                      size="small"
                      type="text"
                      icon={<ReloadOutlined />}
                      onClick={() => onRegenerate(msg)}
                      style={{ color: '#667085', fontSize: 12 }}
                    />
                  </Tooltip>
                )}
                {msg.createdAt && (
                  <span style={{ fontSize: 12, color: '#B6BCC6', marginLeft: 4 }}>
                    {formatMsgTime(msg.createdAt)}
                  </span>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
