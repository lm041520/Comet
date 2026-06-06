import { useState } from 'react'
import { Button, Space, Tag, Tooltip, message as antdMessage } from 'antd'
import {
  CopyOutlined,
  DislikeFilled,
  DislikeOutlined,
  LikeFilled,
  LikeOutlined,
  ReloadOutlined,
  StarFilled,
  StarOutlined,
} from '@ant-design/icons'
import MarkdownMessage from '@/components/MarkdownMessage'
import { favoriteApi } from '@/api/favorites'
import { chatApi } from '@/api/chat'
import { AuthenticatedImage } from '@/components/AuthenticatedImage'
import type { UiMessage } from './types'
import { formatMsgTime, resolveToolMeta } from './types'

export default function MessageItem({
  msg,
  onRegenerate,
}: {
  msg: UiMessage
  onRegenerate?: (msg: UiMessage) => void
}) {
  const isUser = msg.role === 'user'
  // 本地收藏态：null 未收藏；string 已收藏（存 favorite id 供取消）
  const [favId, setFavId] = useState<string | null>(msg.favId ?? null)
  const [favLoading, setFavLoading] = useState(false)
  // 本地反馈态：up | down | null
  const [feedback, setFeedback] = useState<'up' | 'down' | null>(msg.feedback ?? null)

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(msg.content)
      antdMessage.success('已复制')
    } catch {
      antdMessage.error('复制失败')
    }
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

  return (
    <div
      style={{
        display: 'flex',
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        marginBottom: 24,
      }}
    >
      <div style={{ maxWidth: '82%' }}>
        {/* 工具调用标记（AI 消息） */}
        {!isUser && msg.toolCalls && msg.toolCalls.length > 0 && (
          <Space size={[4, 4]} wrap style={{ marginBottom: 8 }}>
            {msg.toolCalls.map((tc, i) => {
              const meta = resolveToolMeta(tc.tool)
              return (
                <Tooltip key={i} title={tc.query}>
                  <Tag color="blue" style={{ borderRadius: 12, fontSize: 13, padding: '2px 10px' }}>
                    {meta.icon} {meta.label}
                  </Tag>
                </Tooltip>
              )
            })}
          </Space>
        )}

        <div
          style={{
            background: isUser ? '#155EEF' : '#F7F8FA',
            color: isUser ? '#fff' : '#1D2129',
            padding: isUser ? '12px 16px' : '14px 18px',
            borderRadius: 14,
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

          {isUser ? (
            <span style={{ whiteSpace: 'pre-wrap', fontSize: 16 }}>{msg.content}</span>
          ) : (
            <MarkdownMessage content={msg.content || (msg.streaming ? '思考中…' : '')} />
          )}
        </div>

        {/* 用户消息复制按钮 + 时间（右对齐） */}
        {isUser && msg.content && (
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

        {/* 引用来源 + 复制按钮（AI 消息） */}
        {!isUser && (
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
