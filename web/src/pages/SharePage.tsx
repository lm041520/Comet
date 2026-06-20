import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Spin, Result, Button } from 'antd'
import MarkdownMessage from '@/components/MarkdownMessage'
import { shareApi, type SharePublic } from '@/api/shares'
import { splitBubbles, hasBubbleSep } from '@/pages/chat/types'
import logo from '@/images/logo.png'

// 对话分享公开查看页（无需登录）：只读渲染快照消息。
export default function SharePage() {
  const { token } = useParams<{ token: string }>()
  const navigate = useNavigate()
  const [data, setData] = useState<SharePublic | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!token) return
    shareApi
      .getPublic(token)
      .then(({ data }) => setData(data))
      .catch((e) => setError((e as Error).message || '分享不存在或已失效'))
      .finally(() => setLoading(false))
  }, [token])

  if (loading) {
    return (
      <div className="share-loading">
        <Spin size="large" />
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="share-page">
        <Result
          status="404"
          title="分享不可用"
          subTitle={error || '该分享链接不存在、已取消或已过期'}
          extra={
            <Button type="primary" onClick={() => navigate('/')}>
              去彗记看看
            </Button>
          }
        />
      </div>
    )
  }

  return (
    <div className="share-page">
      <div className="share-container">
        <div className="share-header">
          <img src={logo} alt="彗记" className="share-logo" />
          <div>
            <div className="share-title">{data.title}</div>
            <div className="share-sub">来自彗记 Comet 的对话分享</div>
          </div>
        </div>

        <div className="share-body">
          {data.messages.map((m, i) => {
            const isUser = m.role === 'user'
            // 右侧「我」：单聊 user（无名） 或 群聊里分享者本人的发言；其他真人靠左具名
            const onRight = isUser && (!m.sender_name || !!m.is_me)
            const leftName = m.sender_name || data.ai_name
            // 左侧头像：真人用真人头像；AI 角色群聊用自己头像、单聊回退全局 ai_avatar
            const leftAvatar = isUser
              ? m.sender_avatar
              : m.sender_name
                ? m.sender_avatar
                : m.sender_avatar || data.ai_avatar
            return (
              <div
                key={i}
                className={`share-msg ${onRight ? 'share-msg-user' : 'share-msg-ai'}`}
              >
                {onRight ? (
                  data.user_avatar ? (
                    <img src={data.user_avatar} alt="我" className="share-avatar share-avatar-ai" />
                  ) : (
                    <div className="share-avatar share-avatar-user">我</div>
                  )
                ) : leftAvatar ? (
                  <img src={leftAvatar} alt={leftName || 'AI'} className="share-avatar share-avatar-ai" />
                ) : leftName ? (
                  <div className="share-avatar share-avatar-user">{leftName.slice(0, 1)}</div>
                ) : (
                  <img src={logo} alt="AI" className="share-avatar share-avatar-ai" />
                )}
                <div className="share-bubble-wrap">
                  {!onRight && leftName && <div className="share-sender">{leftName}</div>}
                  {!isUser && hasBubbleSep(m.content) ? (
                    splitBubbles(m.content).map((seg, k) => (
                      <div className="share-bubble" key={k} style={{ marginBottom: 6 }}>
                        <MarkdownMessage content={seg} />
                      </div>
                    ))
                  ) : (
                    <div className="share-bubble">
                      {m.images && m.images.length > 0 && (
                        <div className="share-images">
                          {m.images.map((src, k) => (
                            <img key={k} src={src} alt="" className="share-image" />
                          ))}
                        </div>
                      )}
                      {isUser ? (
                        m.content && (
                          <span style={{ whiteSpace: 'pre-wrap' }}>{m.content}</span>
                        )
                      ) : (
                        <MarkdownMessage content={m.content} />
                      )}
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>

        <div className="share-footer">
          <span>本页内容由用户分享 · 由</span>
          <a onClick={() => navigate('/')}> 彗记 Comet </a>
          <span>生成</span>
        </div>
      </div>
    </div>
  )
}
