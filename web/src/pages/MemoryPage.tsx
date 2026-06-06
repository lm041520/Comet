import { useEffect, useRef, useState } from 'react'
import {
  Button,
  Card,
  Empty,
  Input,
  Popconfirm,
  Segmented,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import {
  BulbOutlined,
  ClockCircleOutlined,
  ClusterOutlined,
  DeleteOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  StarFilled,
  StarOutlined,
} from '@ant-design/icons'
import {
  memoryApi,
  type Community,
  type CommunityMember,
  type MemoryHit,
  type MemoryProfile,
  type ProfileEntity,
  type TimelineEvent,
} from '@/api/memories'
import { favoriteApi } from '@/api/favorites'

const { Text, Paragraph } = Typography

export default function MemoryPage() {
  const [mode, setMode] = useState<'profile' | 'community' | 'timeline' | 'search'>('profile')

  return (
    <div className="fluid-page">
      <Card
        title="记忆"
        extra={
          <Segmented
            value={mode}
            onChange={(v) => setMode(v as 'profile' | 'community' | 'timeline' | 'search')}
            options={[
              { label: '我的画像', value: 'profile', icon: <BulbOutlined /> },
              { label: '主题社区', value: 'community', icon: <ClusterOutlined /> },
              { label: '时间线', value: 'timeline', icon: <ClockCircleOutlined /> },
              { label: '记忆检索', value: 'search', icon: <SearchOutlined /> },
            ]}
          />
        }
      >
        {mode === 'profile' ? (
          <ProfilePanel />
        ) : mode === 'community' ? (
          <CommunityPanel />
        ) : mode === 'timeline' ? (
          <TimelinePanel />
        ) : (
          <SearchPanel />
        )}
      </Card>
    </div>
  )
}

// ── 我的画像：主动记住输入 + 实体按类型分组卡片 ──
function ProfilePanel() {
  const [profile, setProfile] = useState<MemoryProfile | null>(null)
  const [loading, setLoading] = useState(false)
  const [text, setText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [consolidating, setConsolidating] = useState(false)
  // 已收藏的记忆实体：entity_id -> favorite_id（用于高亮与取消）
  const [favMap, setFavMap] = useState<Record<string, string>>({})
  const pollRef = useRef<number | null>(null)
  const pollCount = useRef(0)

  const loadFavorites = async () => {
    try {
      const { data } = await favoriteApi.list('memory')
      const map: Record<string, string> = {}
      data.forEach((f) => {
        map[f.target_id] = f.id
      })
      setFavMap(map)
    } catch {
      // 收藏状态加载失败不影响画像
    }
  }

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await memoryApi.profile()
      setProfile(data)
      loadFavorites()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current)
    }
  }, [])

  const onRemember = async () => {
    const value = text.trim()
    if (!value) {
      message.warning('请输入要记住的内容')
      return
    }
    setSubmitting(true)
    try {
      await memoryApi.remember(value)
      message.success('已提交，正在萃取记忆，稍后自动刷新')
      setText('')
      // 萃取是异步的，轮询几次刷新画像
      pollCount.current = 0
      if (pollRef.current) window.clearInterval(pollRef.current)
      pollRef.current = window.setInterval(() => {
        pollCount.current += 1
        load()
        if (pollCount.current >= 6 && pollRef.current) {
          window.clearInterval(pollRef.current)
          pollRef.current = null
        }
      }, 4000)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  const onDeleteEntity = async (id: string) => {
    try {
      await memoryApi.deleteEntity(id)
      message.success('已删除')
      load()
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const onConsolidate = async () => {
    setConsolidating(true)
    try {
      const { data } = await memoryApi.consolidate()
      message.success(
        `巩固完成：提升 ${data.promoted_entities} 个实体进长期记忆，增强 ${data.enhanced_profiles} 个画像`,
      )
      load()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setConsolidating(false)
    }
  }

  const onFavoriteEntity = async (ent: ProfileEntity) => {
    const existingFavId = favMap[ent.id]
    try {
      if (existingFavId) {
        // 已收藏 → 取消
        await favoriteApi.remove(existingFavId)
        setFavMap((prev) => {
          const next = { ...prev }
          delete next[ent.id]
          return next
        })
        message.success('已取消收藏')
      } else {
        // 未收藏 → 收藏
        const { data } = await favoriteApi.add('memory', ent.id, {
          title: ent.name,
          summary: ent.description,
        })
        setFavMap((prev) => ({ ...prev, [ent.id]: data.id }))
        message.success('已收藏')
      }
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      {/* 主动记住 */}
      <Space.Compact style={{ width: '100%' }}>
        <Input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onPressEnter={onRemember}
          placeholder="告诉我一些值得长期记住的事，例如：我在腾讯做后端，养了只叫多多的小狗"
          size="large"
          allowClear
        />
        <Button
          type="primary"
          size="large"
          icon={<PlusOutlined />}
          loading={submitting}
          onClick={onRemember}
        >
          记住
        </Button>
      </Space.Compact>

      {loading && !profile ? (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin />
        </div>
      ) : !profile || profile.total === 0 ? (
        <Empty description="还没有记忆。主动记住一些事，或在对话中聊聊你自己，我会自动记住" />
      ) : (
        <>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <Text type="secondary">
              已记住 {profile.total} 个实体，覆盖 {profile.groups.length} 个类型
            </Text>
            <Button size="small" loading={consolidating} onClick={onConsolidate}>
              记忆巩固
            </Button>
          </div>
          {profile.groups.map((group) => (
            <div key={group.type}>
              <div style={{ marginBottom: 10 }}>
                <Tag color="blue" style={{ fontSize: 14, padding: '2px 10px' }}>
                  {group.type}
                </Tag>
                <Text type="secondary" style={{ fontSize: 13 }}>
                  {group.entities.length} 项
                </Text>
              </div>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fill, minmax(16rem, 1fr))',
                  gap: 12,
                  marginBottom: 8,
                }}
              >
                {group.entities.map((ent) => (
                  <Card key={ent.id} size="small" styles={{ body: { padding: 14 } }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                      <Space size={4}>
                        <Text strong style={{ fontSize: 15 }}>
                          {ent.name}
                        </Text>
                        {ent.memory_layer === 'long_term' && (
                          <Tag color="gold" style={{ fontSize: 11, lineHeight: '16px', margin: 0 }}>
                            长期
                          </Tag>
                        )}
                      </Space>
                      <Space size={4}>
                        {favMap[ent.id] ? (
                          <StarFilled
                            onClick={() => onFavoriteEntity(ent)}
                            style={{ color: '#FAAD14', cursor: 'pointer' }}
                          />
                        ) : (
                          <StarOutlined
                            onClick={() => onFavoriteEntity(ent)}
                            style={{ color: '#C0C4CC', cursor: 'pointer' }}
                          />
                        )}
                        <Popconfirm title="删除该记忆实体？" onConfirm={() => onDeleteEntity(ent.id)}>
                          <DeleteOutlined style={{ color: '#C0C4CC' }} />
                        </Popconfirm>
                      </Space>
                    </div>
                    {ent.description && (
                      <Paragraph
                        type="secondary"
                        style={{ margin: '4px 0 0', fontSize: 13 }}
                        ellipsis={{ rows: 2, expandable: true, symbol: '展开' }}
                      >
                        {ent.description}
                      </Paragraph>
                    )}
                    {ent.aliases.length > 0 && (
                      <div style={{ marginTop: 6 }}>
                        {ent.aliases.map((a) => (
                          <Tag key={a} style={{ fontSize: 12 }}>
                            {a}
                          </Tag>
                        ))}
                      </div>
                    )}
                    {ent.relations.length > 0 && (
                      <div style={{ marginTop: 8, paddingLeft: 8, borderLeft: '2px solid #EEF4FF' }}>
                        {ent.relations.slice(0, 4).map((rel, i) => (
                          <div key={i} style={{ fontSize: 12.5, color: '#475467', lineHeight: 1.8 }}>
                            <Text type="secondary">{rel.predicate}</Text> {rel.object_name}
                          </div>
                        ))}
                      </div>
                    )}
                    {ent.traits && ent.traits.length > 0 && (
                      <div style={{ marginTop: 8 }}>
                        {ent.traits.map((t) => (
                          <Tag key={t} color="purple" style={{ fontSize: 12 }}>
                            {t}
                          </Tag>
                        ))}
                      </div>
                    )}
                    {ent.core_facts && ent.core_facts.length > 0 && (
                      <div style={{ marginTop: 6 }}>
                        {ent.core_facts.slice(0, 4).map((f, i) => (
                          <div key={i} style={{ fontSize: 12.5, color: '#155EEF', lineHeight: 1.7 }}>
                            ✦ {f}
                          </div>
                        ))}
                      </div>
                    )}
                  </Card>
                ))}
              </div>
            </div>
          ))}
        </>
      )}
    </Space>
  )
}

// ── 记忆检索 ──
function SearchPanel() {
  const [query, setQuery] = useState('')
  const [searching, setSearching] = useState(false)
  const [hits, setHits] = useState<MemoryHit[]>([])

  const onSearch = async () => {
    const q = query.trim()
    if (!q) {
      message.warning('请输入检索关键词')
      return
    }
    setSearching(true)
    try {
      const { data } = await memoryApi.search(q, 10)
      setHits(data)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSearching(false)
    }
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Space.Compact style={{ width: '100%' }}>
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onPressEnter={onSearch}
          placeholder="按语义检索记忆，例如：我养的宠物、我的工作"
          size="large"
          allowClear
        />
        <Button type="primary" size="large" loading={searching} icon={<SearchOutlined />} onClick={onSearch}>
          检索
        </Button>
      </Space.Compact>

      {hits.length === 0 ? (
        <Empty description="输入关键词，从记忆图谱里召回相关实体与关系" />
      ) : (
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          {hits.map((h) => (
            <Card key={h.id} size="small" styles={{ body: { padding: 16 } }}>
              <Space size="small" style={{ marginBottom: 6 }}>
                <Text strong>{h.name}</Text>
                <Tag color="blue">{h.type}</Tag>
                <Tooltip title="相关度">
                  <Tag>{h.score}</Tag>
                </Tooltip>
              </Space>
              {h.description && (
                <Paragraph type="secondary" style={{ margin: '4px 0' }}>
                  {h.description}
                </Paragraph>
              )}
              {h.aliases.length > 0 && (
                <div style={{ marginBottom: 6 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>别名：</Text>
                  {h.aliases.map((a) => (
                    <Tag key={a}>{a}</Tag>
                  ))}
                </div>
              )}
              {h.relations.length > 0 && (
                <div style={{ paddingLeft: 8, borderLeft: '2px solid #EEF4FF' }}>
                  {h.relations.map((rel, i) => (
                    <div key={i} style={{ fontSize: 13, color: '#475467' }}>
                      {h.name} <Text type="secondary">{rel.predicate}</Text> {rel.object_name}
                    </div>
                  ))}
                </div>
              )}
            </Card>
          ))}
        </Space>
      )}
    </Space>
  )
}


// ── 主题社区：社区卡片 + 展开看成员实体 ──
function CommunityPanel() {
  const [communities, setCommunities] = useState<Community[]>([])
  const [loading, setLoading] = useState(false)
  const [reclustering, setReclustering] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [members, setMembers] = useState<Record<string, CommunityMember[]>>({})

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await memoryApi.communities()
      setCommunities(data)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const onRecluster = async () => {
    setReclustering(true)
    try {
      await memoryApi.recluster()
      message.success('聚类完成')
      load()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setReclustering(false)
    }
  }

  const toggle = async (id: string) => {
    if (expanded === id) {
      setExpanded(null)
      return
    }
    setExpanded(id)
    if (!members[id]) {
      try {
        const { data } = await memoryApi.communityMembers(id)
        setMembers((prev) => ({ ...prev, [id]: data }))
      } catch (e) {
        message.error((e as Error).message)
      }
    }
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Text type="secondary">
          相关实体自动聚成主题社区，反映你记忆里的知识结构
        </Text>
        <Button icon={<ReloadOutlined />} loading={reclustering} onClick={onRecluster}>
          重新聚类
        </Button>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin />
        </div>
      ) : communities.length === 0 ? (
        <Empty description="还没有社区。记忆积累后会自动聚类，或点「重新聚类」" />
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(18rem, 1fr))',
            gap: 12,
          }}
        >
          {communities.map((c) => (
            <Card
              key={c.id}
              size="small"
              hoverable
              styles={{ body: { padding: 14 } }}
              onClick={() => toggle(c.id)}
            >
              <Space style={{ marginBottom: 4 }}>
                <Text strong style={{ fontSize: 15 }}>{c.name}</Text>
                <Tag color="purple">{c.member_count} 个实体</Tag>
              </Space>
              <Paragraph type="secondary" style={{ margin: 0, fontSize: 13 }} ellipsis={{ rows: 2 }}>
                {c.summary}
              </Paragraph>
              {expanded === c.id && members[c.id] && (
                <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid #F0F0F0' }}>
                  {members[c.id].map((m) => (
                    <div key={m.id} style={{ fontSize: 13, marginBottom: 4 }}>
                      <Text strong>{m.name}</Text>{' '}
                      <Tag>{m.type}</Tag>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </Space>
  )
}


// ── 时间线：事件按时间倒序竖线展示 ──
function TimelinePanel() {
  const [events, setEvents] = useState<TimelineEvent[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    memoryApi
      .timeline()
      .then(({ data }) => setEvents(data))
      .catch((e) => message.error((e as Error).message))
      .finally(() => setLoading(false))
  }, [])

  const fmt = (ev: TimelineEvent) => {
    const raw = ev.event_time || ev.created_at
    if (!raw) return '时间未知'
    const d = new Date(raw)
    if (Number.isNaN(d.getTime())) return String(raw)
    return d.toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' })
  }

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 40 }}>
        <Spin />
      </div>
    )
  }

  if (events.length === 0) {
    return <Empty description="还没有事件。在对话或主动记住中提到带时间的经历，会自动记入时间线" />
  }

  return (
    <div style={{ paddingLeft: 8 }}>
      {events.map((ev) => (
        <div
          key={ev.id}
          style={{
            position: 'relative',
            paddingLeft: 24,
            paddingBottom: 20,
            borderLeft: '2px solid #EEF4FF',
          }}
        >
          <span
            style={{
              position: 'absolute',
              left: -7,
              top: 2,
              width: 12,
              height: 12,
              borderRadius: '50%',
              background: '#155EEF',
              border: '2px solid #fff',
            }}
          />
          <Text type="secondary" style={{ fontSize: 13 }}>
            {fmt(ev)}
          </Text>
          <div style={{ margin: '2px 0 4px' }}>
            <Text strong style={{ fontSize: 15 }}>
              {ev.title}
            </Text>
          </div>
          {ev.description && (
            <Paragraph type="secondary" style={{ margin: '0 0 6px', fontSize: 13.5 }}>
              {ev.description}
            </Paragraph>
          )}
          {ev.participants.length > 0 && (
            <Space size={4} wrap>
              {ev.participants.map((p) => (
                <Tag key={p.id} color="blue" style={{ fontSize: 12 }}>
                  {p.name}
                </Tag>
              ))}
            </Space>
          )}
        </div>
      ))}
    </div>
  )
}
