import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Spin, Result, Button } from 'antd'
import MarkdownMessage from '@/components/MarkdownMessage'
import { shareApi, type SharePublic } from '@/api/shares'
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
            // 群聊：每条 AI 消息带自己的发言人头像/名字
            const aiAvatar = m.sender_avatar || data.ai_avatar
            const aiName = m.sender_name || data.ai_name
            return (
              <div
                key={i}
                className={`share-msg ${isUser ? 'share-msg-user' : 'share-msg-ai'}`}
              >
                {isUser ? (
                  data.user_avatar ? (
                    <img src={data.user_avatar} alt="我" className="share-avatar share-avatar-ai" />
                  ) : (
                    <div className="share-avatar share-avatar-user">我</div>
                  )
                ) : aiAvatar ? (
                  <img src={aiAvatar} alt={aiName || 'AI'} className="share-avatar share-avatar-ai" />
                ) : (
                  <img src={logo} alt="AI" className="share-avatar share-avatar-ai" />
                )}
                <div className="share-bubble-wrap">
                  {!isUser && aiName && <div className="share-sender">{aiName}</div>}
                  <div className="share-bubble">
                    {isUser ? (
                      <span style={{ whiteSpace: 'pre-wrap' }}>{m.content}</span>
                    ) : (
                      <MarkdownMessage content={m.content} />
                    )}
                  </div>
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
