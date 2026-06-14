import { useCallback, useEffect, useState } from 'react'
import { Button, Divider, Empty, Input, Modal, Popconfirm, Select, Space, Tag, message } from 'antd'
import { CopyOutlined, DeleteOutlined, LinkOutlined } from '@ant-design/icons'
import { shareApi, type Share } from '@/api/shares'
import { copyText } from '@/utils/clipboard'

interface Props {
  open: boolean
  conversationId?: string
  onClose: () => void
}

const linkOf = (s: Share) => `${window.location.origin}/s/${s.share_token}`

// 对话分享弹窗：生成只读链接 + 复制 + 选过期 + 取消；并列出「我的分享」可管理删除。
export default function ShareModal({ open, conversationId, onClose }: Props) {
  const [share, setShare] = useState<Share | null>(null)
  const [expireDays, setExpireDays] = useState<number | null>(null)
  const [title, setTitle] = useState('')
  const [loading, setLoading] = useState(false)
  const [list, setList] = useState<Share[]>([])

  const loadList = useCallback(async () => {
    try {
      const { data } = await shareApi.list()
      // 只展示有效分享（取消的保留痕迹但不在管理列表显示）
      setList(data.filter((s) => s.is_active))
    } catch {
      // 列表加载失败不阻断
    }
  }, [])

  useEffect(() => {
    if (open) {
      setShare(null)
      setExpireDays(null)
      setTitle('')
      loadList()
    }
  }, [open, conversationId, loadList])

  const link = share ? linkOf(share) : ''

  const onGenerate = async () => {
    if (!conversationId) {
      message.warning('请先选择一个会话')
      return
    }
    setLoading(true)
    try {
      const { data } = await shareApi.create(conversationId, expireDays, title.trim() || undefined)
      setShare(data)
      message.success('已生成分享链接')
      loadList()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const onCopy = async (text: string) => {
    const ok = await copyText(text)
    if (ok) message.success('链接已复制')
    else message.error('复制失败')
  }

  const onRevoke = async (id: string, isCurrent: boolean) => {
    try {
      await shareApi.revoke(id)
      message.success('已取消分享，链接失效')
      if (isCurrent) setShare(null)
      loadList()
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  return (
    <Modal open={open} onCancel={onClose} footer={null} title="分享对话" width={560}>
      <p style={{ color: '#667085', fontSize: 13, marginTop: 4 }}>
        生成只读分享链接，他人无需登录即可查看。分享为快照，之后继续聊不影响已分享内容。
      </p>

      {!share ? (
        <Space direction="vertical" size={14} style={{ width: '100%', marginTop: 8 }}>
          <div>
            <div className="share-field-label">分享标题</div>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="留空则用会话标题"
              maxLength={256}
            />
          </div>
          <div>
            <div className="share-field-label">有效期</div>
            <Select
              value={expireDays}
              onChange={setExpireDays}
              style={{ width: '100%' }}
              options={[
                { value: null, label: '永久有效' },
                { value: 7, label: '7 天后过期' },
                { value: 30, label: '30 天后过期' },
              ]}
            />
          </div>
          <Button type="primary" icon={<LinkOutlined />} loading={loading} onClick={onGenerate} block>
            生成 / 刷新本对话的分享链接
          </Button>
        </Space>
      ) : (
        <Space direction="vertical" style={{ width: '100%', marginTop: 8 }}>
          <Space.Compact style={{ width: '100%' }}>
            <Input value={link} readOnly />
            <Button type="primary" icon={<CopyOutlined />} onClick={() => onCopy(link)}>
              复制
            </Button>
          </Space.Compact>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 12, color: '#98A2B3' }}>
              {share.expire_at
                ? `将于 ${new Date(share.expire_at).toLocaleDateString()} 过期`
                : '永久有效'}
            </span>
            <Button type="text" danger size="small" onClick={() => onRevoke(share.id, true)}>
              取消分享
            </Button>
          </div>
        </Space>
      )}

      <Divider style={{ margin: '18px 0 12px' }}>我的分享</Divider>
      {list.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有分享过对话" />
      ) : (
        <div className="share-list">
          {list.map((s) => (
            <div key={s.id} className="share-list-item">
              <div className="share-list-info">
                <div className="share-list-title">{s.title}</div>
                <div className="share-list-meta">
                  <span>浏览 {s.view_count}</span>
                  {s.expire_at ? (
                    <Tag color="orange">
                      {new Date(s.expire_at).toLocaleDateString()} 过期
                    </Tag>
                  ) : (
                    <Tag>永久</Tag>
                  )}
                </div>
              </div>
              <Space size={2}>
                <Button
                  type="text"
                  size="small"
                  icon={<CopyOutlined />}
                  onClick={() => onCopy(linkOf(s))}
                />
                <Popconfirm
                  title="取消该分享？"
                  description="取消后链接立即失效"
                  okButtonProps={{ danger: true }}
                  okText="取消分享"
                  cancelText="再想想"
                  onConfirm={() => onRevoke(s.id, false)}
                >
                  <Button type="text" size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </Space>
            </div>
          ))}
        </div>
      )}
    </Modal>
  )
}
