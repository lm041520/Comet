import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Button,
  Card,
  Drawer,
  Empty,
  Input,
  Popconfirm,
  Segmented,
  Space,
  Spin,
  Switch,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import {
  CheckCircleOutlined,
  AuditOutlined,
  BulbOutlined,
  ClockCircleOutlined,
  ClusterOutlined,
  DeleteOutlined,
  ExclamationCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  StarFilled,
  StarOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import {
  memoryApi,
  type Community,
  type CommunityMember,
  type Insight,
  type MemoryHit,
  type MemoryProfile,
  type ProfileEntity,
  type TimelineEvent,
} from '@/api/memories'
import { favoriteApi } from '@/api/favorites'
import ReviewPanel from '@/components/memory/ReviewPanel'

const { Text, Paragraph } = Typography

type TrustTone = 'high' | 'medium' | 'low'

function trustTone(confidence?: number | null): TrustTone {
  const value = typeof confidence === 'number' ? confidence : 0.8
  if (value >= 0.85) return 'high'
  if (value >= 0.75) return 'medium'
  return 'low'
}

function trustLabel(confidence?: number | null) {
  const tone = trustTone(confidence)
  if (tone === 'high') return '高置信'
  if (tone === 'medium') return '中置信'
  return '待确认'
}

function trustColor(confidence?: number | null) {
  const tone = trustTone(confidence)
  if (tone === 'high') return 'success'
  if (tone === 'medium') return 'processing'
  return 'warning'
}

function trustPercent(confidence?: number | null) {
  const value = typeof confidence === 'number' ? confidence : 0.8
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`
}

function TrustTag({ confidence }: { confidence?: number | null }) {
  const low = trustTone(confidence) === 'low'
  return (
    <Tooltip title={`置信度 ${trustPercent(confidence)}`}>
      <Tag
        color={trustColor(confidence)}
        icon={low ? <ExclamationCircleOutlined /> : <CheckCircleOutlined />}
        style={{ margin: 0 }}
      >
        {trustLabel(confidence)}
      </Tag>
    </Tooltip>
  )
}

export default function MemoryPage() {
  const [mode, setMode] = useState<
    'profile' | 'community' | 'timeline' | 'search' | 'review'
  >('profile')

  // 手机端用短标签,否则 5 个 4 字标签在窄屏会被挤成省略号
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== 'undefined' && window.innerWidth <= 768,
  )
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 768px)')
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])

  const tabOptions = [
    { label: isMobile ? '画像' : '我的画像', value: 'profile', icon: <BulbOutlined /> },
    { label: isMobile ? '社区' : '主题社区', value: 'community', icon: <ClusterOutlined /> },
    { label: isMobile ? '时间' : '时间线', value: 'timeline', icon: <ClockCircleOutlined /> },
    { label: isMobile ? '检索' : '记忆检索', value: 'search', icon: <SearchOutlined /> },
    { label: isMobile ? '审查' : '审查纠错', value: 'review', icon: <AuditOutlined /> },
  ]

  return (
    <div className="fluid-page">
      <Card
        title="记忆"
        className="memory-card"
        extra={
          <Segmented
            className="memory-tabs"
            value={mode}
            onChange={(v) =>
              setMode(v as 'profile' | 'community' | 'timeline' | 'search' | 'review')
            }
            options={tabOptions}
          />
        }
      >
        {mode === 'profile' ? (
          <ProfilePanel />
        ) : mode === 'community' ? (
          <CommunityPanel />
        ) : mode === 'timeline' ? (
          <TimelinePanel />
        ) : mode === 'search' ? (
          <SearchPanel />
        ) : (
          <ReviewPanel />
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
      {/* AI 眼中的你（反思引擎归纳的高层理解） */}
      <InsightsBanner />

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
                  gridTemplateColumns: 'repeat(auto-fill, minmax(min(16rem, 100%), 1fr))',
                  gap: 12,
                  marginBottom: 8,
                }}
              >
                {group.entities.map((ent) => (
                  <Card
                    key={ent.id}
                    size="small"
                    className={trustTone(ent.confidence) === 'low' ? 'memory-entity-card memory-entity-card--weak' : 'memory-entity-card'}
                    styles={{ body: { padding: 14 } }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                      <Space size={4} wrap>
                        <Text strong style={{ fontSize: 15 }}>
                          {ent.name}
                        </Text>
                        <TrustTag confidence={ent.confidence} />
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
                            {trustTone(rel.confidence) === 'low' && (
                              <Tag color="warning" style={{ marginRight: 6, fontSize: 11, lineHeight: '16px' }}>
                                待确认
                              </Tag>
                            )}
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

// ── AI 眼中的你：反思引擎归纳的高层理解 ──
function InsightsBanner() {
  const [insights, setInsights] = useState<Insight[]>([])
  const [loading, setLoading] = useState(true)
  const [reflecting, setReflecting] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const COLLAPSE_LIMIT = 6

  const load = async () => {
    try {
      const { data } = await memoryApi.insights()
      setInsights(data)
    } catch {
      // 洞察加载失败不影响画像
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const onReflect = async () => {
    setReflecting(true)
    try {
      const { data } = await memoryApi.reflect()
      if (data.insights > 0) {
        message.success(`已更新对你的理解，共 ${data.insights} 条`)
      } else {
        message.info('记忆还不够多，再多聊聊我就更懂你了')
      }
      load()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setReflecting(false)
    }
  }

  const onDelete = async (id: string) => {
    try {
      await memoryApi.deleteInsight(id)
      setInsights((prev) => prev.filter((x) => x.id !== id))
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  // 加载中或空且未在反思：仍展示一个可触发反思的入口
  return (
    <div className="insight-banner">
      <div className="insight-banner-head">
        <Space size={8}>
          <BulbOutlined style={{ color: '#155EEF', fontSize: 18 }} />
          <span className="insight-banner-title">AI 眼中的你</span>
        </Space>
        <Button
          size="small"
          type="primary"
          ghost
          icon={<ThunderboltOutlined />}
          loading={reflecting}
          onClick={onReflect}
        >
          重新认识你
        </Button>
      </div>

      {loading ? (
        <div style={{ padding: 16, textAlign: 'center' }}>
          <Spin />
        </div>
      ) : insights.length === 0 ? (
        <div className="insight-banner-empty">
          还不太了解你。随着记忆积累，我会慢慢读懂你是个怎样的人（如「持续精进的技术人」），
          也可以点「重新认识你」马上生成。
        </div>
      ) : (
        <>
          <div className="insight-grid">
            {(expanded ? insights : insights.slice(0, COLLAPSE_LIMIT)).map((it) => (
              <div key={it.id} className="insight-item">
                <div className="insight-item-head">
                  <Tag color="geekblue" style={{ margin: 0 }}>
                    {it.theme}
                  </Tag>
                  <TrustTag confidence={it.confidence} />
                  <Popconfirm title="删除这条洞察？" onConfirm={() => onDelete(it.id)}>
                    <DeleteOutlined className="insight-del" />
                  </Popconfirm>
                </div>
                <div className="insight-content">{it.content}</div>
              </div>
            ))}
          </div>
          {insights.length > COLLAPSE_LIMIT && (
            <div style={{ textAlign: 'center', marginTop: 10 }}>
              <Button type="link" onClick={() => setExpanded((v) => !v)}>
                {expanded ? '收起' : `展开全部 ${insights.length} 条`}
              </Button>
            </div>
          )}
        </>
      )}
    </div>
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
                <TrustTag confidence={h.confidence} />
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
                      {trustTone(rel.confidence) === 'low' && (
                        <Tag color="warning" style={{ marginRight: 6, fontSize: 11, lineHeight: '16px' }}>
                          待确认
                        </Tag>
                      )}
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


// ── 主题社区:按成员数排序+过滤小社区+卡片热度配色,点击开 Drawer 看详情 ──
function CommunityPanel() {
  const [communities, setCommunities] = useState<Community[]>([])
  const [loading, setLoading] = useState(false)
  const [reclustering, setReclustering] = useState(false)
  const [showAll, setShowAll] = useState(false)

  // Drawer:社区详情(成员列表)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [activeCommunity, setActiveCommunity] = useState<Community | null>(null)
  const [drawerMembers, setDrawerMembers] = useState<CommunityMember[]>([])
  const [drawerLoading, setDrawerLoading] = useState(false)

  // 手机端:Drawer 改成底部弹出,桌面端保持右侧
  const [isMobile, setIsMobile] = useState(
    typeof window !== 'undefined' ? window.innerWidth <= 768 : false,
  )
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 768px)')
    const onChange = (e: MediaQueryListEvent) => setIsMobile(e.matches)
    setIsMobile(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

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

  const openDrawer = async (c: Community) => {
    setActiveCommunity(c)
    setDrawerOpen(true)
    setDrawerLoading(true)
    setDrawerMembers([])
    try {
      const { data } = await memoryApi.communityMembers(c.id)
      setDrawerMembers(data)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setDrawerLoading(false)
    }
  }

  // 默认只显示 ≥2 成员的「真正聚出来的」社区,1-成员视为噪声,可一键展开
  const visible = useMemo(
    () => (showAll ? communities : communities.filter((c) => c.member_count >= 2)),
    [communities, showAll],
  )
  const hidden = communities.length - visible.length

  // 热度档:统一蓝色家族,只用徽章饱和度区分,不上多色不渐变
  const tierOf = (n: number) => {
    if (n >= 15)
      return {
        // 核心:实心品牌蓝
        badge: { bg: '#155EEF', color: '#fff', border: '#155EEF' },
        accent: '#155EEF',
        label: '核心',
      }
    if (n >= 8)
      return {
        // 主干:浅蓝底深蓝字
        badge: { bg: '#EEF4FF', color: '#155EEF', border: '#dbe6ff' },
        accent: '#155EEF',
        label: '主干',
      }
    if (n >= 4)
      return {
        // 聚集:更淡的蓝
        badge: { bg: '#F4F8FF', color: '#4A7BF5', border: '#e3ecff' },
        accent: '#4A7BF5',
        label: '聚集',
      }
    if (n >= 2)
      return {
        // 初聚:中性灰底
        badge: { bg: '#F4F6F8', color: '#667085', border: '#e7eaee' },
        accent: '#667085',
        label: '初聚',
      }
    return {
      // 孤立:最浅灰
      badge: { bg: '#F7F9FC', color: '#98A2B3', border: '#eef0f4' },
      accent: '#98A2B3',
      label: '孤立',
    }
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {/* 顶栏:说明 + 显示全部开关 + 重新聚类 */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          gap: 12,
          padding: '12px 16px',
          background: '#f7f9fc',
          borderRadius: 10,
        }}
      >
        <ClusterOutlined style={{ color: '#155EEF', fontSize: 16 }} />
        <Text strong style={{ fontSize: 13.5 }}>
          相关实体自动聚成主题社区
        </Text>
        <Text type="secondary" style={{ fontSize: 12 }}>
          按规模降序排列,反映你记忆里的知识结构
        </Text>
        <div style={{ flex: 1 }} />
        {hidden > 0 && (
          <Tooltip title={`隐藏了 ${hidden} 个仅 1 个实体的孤立社区(基本是噪声)`}>
            <Space size={6}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                显示孤立小社区
              </Text>
              <Switch size="small" checked={showAll} onChange={setShowAll} />
            </Space>
          </Tooltip>
        )}
        <Button
          icon={<ReloadOutlined />}
          loading={reclustering}
          onClick={onRecluster}
          size="small"
        >
          重新聚类
        </Button>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin />
        </div>
      ) : visible.length === 0 ? (
        <Empty
          description={
            communities.length === 0
              ? '还没有社区。记忆积累后会自动聚类,或点「重新聚类」'
              : `所有社区都只有 1 个实体,聚类还没有形成结构。打开「显示孤立小社区」可查看 ${communities.length} 个孤立项`
          }
        />
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(min(20rem, 100%), 1fr))',
            gap: 14,
          }}
        >
          {visible.map((c) => {
            const tier = tierOf(c.member_count)
            return (
              <div
                key={c.id}
                onClick={() => openDrawer(c)}
                style={{
                  background: '#ffffff',
                  border: '1px solid #eef0f4',
                  borderRadius: 12,
                  padding: '16px 18px',
                  cursor: 'pointer',
                  minWidth: 0,
                  transition:
                    'transform 0.18s, box-shadow 0.18s, border-color 0.18s',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.transform = 'translateY(-2px)'
                  e.currentTarget.style.borderColor = '#155EEF'
                  e.currentTarget.style.boxShadow =
                    '0 8px 18px -12px rgba(21, 94, 239, 0.3)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.transform = ''
                  e.currentTarget.style.borderColor = '#eef0f4'
                  e.currentTarget.style.boxShadow = ''
                }}
              >
                {/* 标题行 */}
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    marginBottom: 8,
                  }}
                >
                  <Text
                    strong
                    style={{
                      fontSize: 15.5,
                      color: '#171719',
                      flex: 1,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                    title={c.name}
                  >
                    {c.name}
                  </Text>
                  <span
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 4,
                      padding: '2px 10px',
                      borderRadius: 999,
                      fontSize: 12,
                      fontWeight: 600,
                      lineHeight: 1.5,
                      background: tier.badge.bg,
                      color: tier.badge.color,
                      border: `1px solid ${tier.badge.border}`,
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {c.member_count} 个实体
                  </span>
                </div>
                {/* 摘要 */}
                <Paragraph
                  type="secondary"
                  style={{
                    margin: 0,
                    fontSize: 13,
                    lineHeight: 1.65,
                    minHeight: 42,
                    color: '#667085',
                  }}
                  ellipsis={{ rows: 2, tooltip: c.summary }}
                >
                  {c.summary || '暂无摘要 —— 重新聚类可让 AI 自动生成主题概括'}
                </Paragraph>
                {/* 底部:档位 + 引导 */}
                <div
                  style={{
                    marginTop: 12,
                    paddingTop: 10,
                    borderTop: '1px solid #f4f6f8',
                    fontSize: 11.5,
                    color: '#98A2B3',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                  }}
                >
                  <span style={{ color: tier.accent }}>· {tier.label}</span>
                  <span>点击查看成员 →</span>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* 社区详情 Drawer */}
      <Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title={
          activeCommunity ? (
            <Space size={8}>
              <ClusterOutlined style={{ color: '#155EEF' }} />
              <span>{activeCommunity.name}</span>
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  padding: '2px 10px',
                  borderRadius: 999,
                  fontSize: 12,
                  fontWeight: 600,
                  background: tierOf(activeCommunity.member_count).badge.bg,
                  color: tierOf(activeCommunity.member_count).badge.color,
                  border: `1px solid ${
                    tierOf(activeCommunity.member_count).badge.border
                  }`,
                }}
              >
                {activeCommunity.member_count} 个实体
              </span>
            </Space>
          ) : (
            '社区详情'
          )
        }
        width={isMobile ? '100%' : Math.min(560, window.innerWidth - 24)}
        height={isMobile ? '85vh' : undefined}
        placement={isMobile ? 'bottom' : 'right'}
        styles={
          isMobile
            ? {
                content: { borderTopLeftRadius: 16, borderTopRightRadius: 16 },
                body: { padding: '16px 16px 24px' },
              }
            : undefined
        }
        destroyOnHidden
      >
        {activeCommunity?.summary && (
          <div
            style={{
              padding: '12px 14px',
              background: '#f7f9fc',
              borderRadius: 10,
              fontSize: 13,
              color: '#475467',
              lineHeight: 1.7,
              marginBottom: 16,
              borderLeft: '3px solid #155EEF',
            }}
          >
            {activeCommunity.summary}
          </div>
        )}
        <div
          style={{
            display: 'flex',
            alignItems: 'baseline',
            justifyContent: 'space-between',
            marginBottom: 10,
          }}
        >
          <Text strong style={{ fontSize: 14 }}>
            社区成员
          </Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {drawerLoading
              ? '加载中…'
              : `共 ${drawerMembers.length} 个`}
          </Text>
        </div>
        {drawerLoading ? (
          <div style={{ textAlign: 'center', padding: 32 }}>
            <Spin />
          </div>
        ) : drawerMembers.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <div style={{ color: '#98A2B3', fontSize: 13 }}>
                社区记录的成员都已被移除 ——
                <br />
                点「重新聚类」可清理这条历史残留
              </div>
            }
          />
        ) : (
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            {drawerMembers.map((m) => (
              <div
                key={m.id}
                style={{
                  background: '#fff',
                  border: '1px solid #eef0f4',
                  borderRadius: 10,
                  padding: '10px 12px',
                  transition: 'border-color 0.18s, box-shadow 0.18s',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = '#cfdcff'
                  e.currentTarget.style.boxShadow =
                    '0 4px 10px -8px rgba(21, 94, 239, 0.4)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = '#eef0f4'
                  e.currentTarget.style.boxShadow = ''
                }}
              >
                <Space size={6} style={{ marginBottom: 4 }} wrap>
                  <Text strong style={{ fontSize: 14 }}>
                    {m.name}
                  </Text>
                  {m.type && (
                    <Tag color="blue" style={{ margin: 0 }}>
                      {m.type}
                    </Tag>
                  )}
                </Space>
                {m.description && (
                  <Paragraph
                    type="secondary"
                    style={{
                      margin: '2px 0 0',
                      fontSize: 12.5,
                      lineHeight: 1.6,
                    }}
                    ellipsis={{ rows: 2, tooltip: m.description }}
                  >
                    {m.description}
                  </Paragraph>
                )}
                {m.aliases && m.aliases.length > 0 && (
                  <div style={{ marginTop: 6 }}>
                    {m.aliases.map((a, i) => (
                      <Tag
                        key={i}
                        style={{
                          margin: '0 4px 0 0',
                          fontSize: 11,
                          color: '#667085',
                          background: '#f7f9fc',
                          border: '1px dashed #d6dae0',
                        }}
                      >
                        别名:{a}
                      </Tag>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </Space>
        )}
      </Drawer>
    </Space>
  )
}


// ── 时间线:按日期智能分桶(今天/昨天/近7天/本月/按月份),卡片化事件 ──
type TimeBucket = {
  key: string
  label: string
  hint?: string // 副标题,如 "6月21日 周六"
  order: number
  events: TimelineEvent[]
}

function bucketize(events: TimelineEvent[]): TimeBucket[] {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yesterday = new Date(today.getTime() - 86_400_000)
  const week7Ago = new Date(today.getTime() - 6 * 86_400_000)
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1)
  const weekdays = ['日', '一', '二', '三', '四', '五', '六']

  const buckets: Record<string, TimeBucket> = {}
  const put = (
    key: string,
    label: string,
    order: number,
    ev: TimelineEvent,
    hint?: string,
  ) => {
    if (!buckets[key])
      buckets[key] = { key, label, hint, order, events: [] }
    buckets[key].events.push(ev)
  }

  for (const ev of events) {
    const raw = ev.event_time || ev.created_at
    if (!raw) {
      put('unknown', '时间未知', 99999, ev)
      continue
    }
    const d = new Date(raw)
    if (Number.isNaN(d.getTime())) {
      put('unknown', '时间未知', 99999, ev)
      continue
    }
    const day = new Date(d.getFullYear(), d.getMonth(), d.getDate())
    const hint = `${d.getMonth() + 1} 月 ${d.getDate()} 日 · 周${weekdays[d.getDay()]}`

    if (day.getTime() === today.getTime()) {
      put('today', '今天', 0, ev, hint)
    } else if (day.getTime() === yesterday.getTime()) {
      put('yesterday', '昨天', 1, ev, hint)
    } else if (day >= week7Ago && day < yesterday) {
      put('week', '近 7 天', 2, ev)
    } else if (day >= monthStart && day < week7Ago) {
      put('month', '本月更早', 3, ev)
    } else {
      const ym = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
      // 较新的月份排前面:用负时间戳缩放
      const order = 10 - d.getTime() / 1e13
      put(ym, `${d.getFullYear()} 年 ${d.getMonth() + 1} 月`, order, ev)
    }
  }

  return Object.values(buckets).sort((a, b) => a.order - b.order)
}

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

  const buckets = useMemo(() => bucketize(events), [events])

  // 一天内只显示 HH:mm,跨天显示 M月D日
  const fmtEventTime = (ev: TimelineEvent, bucketKey: string) => {
    const raw = ev.event_time || ev.created_at
    if (!raw) return '时间未知'
    const d = new Date(raw)
    if (Number.isNaN(d.getTime())) return String(raw)
    if (bucketKey === 'today' || bucketKey === 'yesterday') {
      const hh = String(d.getHours()).padStart(2, '0')
      const mm = String(d.getMinutes()).padStart(2, '0')
      return `${hh}:${mm}`
    }
    return `${d.getMonth() + 1}月${d.getDate()}日`
  }

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 40 }}>
        <Spin />
      </div>
    )
  }

  if (events.length === 0) {
    return (
      <Empty description="还没有事件。在对话或主动记住中提到带时间的经历,会自动记入时间线" />
    )
  }

  return (
    <div>
      {/* 顶部统计 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '10px 14px',
          background: 'linear-gradient(135deg, #f0f7ff 0%, #ffffff 70%)',
          border: '1px solid #dbe6ff',
          borderRadius: 12,
          marginBottom: 18,
        }}
      >
        <ClockCircleOutlined style={{ color: '#155EEF', fontSize: 16 }} />
        <Text strong style={{ fontSize: 14 }}>
          共 {events.length} 条带时间的事件
        </Text>
        <Text type="secondary" style={{ fontSize: 12 }}>
          · 按时间倒序展示,提到「日期」的对话会自动记入
        </Text>
      </div>

      {/* 分桶时间线 */}
      <Space direction="vertical" size={24} style={{ width: '100%' }}>
        {buckets.map((b) => (
          <div key={b.key}>
            {/* 桶头 */}
            <div
              style={{
                display: 'flex',
                alignItems: 'baseline',
                gap: 10,
                marginBottom: 12,
                paddingBottom: 6,
                borderBottom: '1px solid #f0f1f3',
              }}
            >
              <Text strong style={{ fontSize: 15, color: '#171719' }}>
                {b.label}
              </Text>
              {b.hint && (
                <Text type="secondary" style={{ fontSize: 12.5 }}>
                  {b.hint}
                </Text>
              )}
              <div style={{ flex: 1 }} />
              <span
                style={{
                  fontSize: 12,
                  color: '#667085',
                  background: '#f7f9fc',
                  padding: '1px 8px',
                  borderRadius: 999,
                }}
              >
                {b.events.length} 条
              </span>
            </div>

            {/* 事件列表 */}
            <div style={{ paddingLeft: 8 }}>
              {b.events.map((ev, idx) => (
                <div
                  key={ev.id}
                  style={{
                    position: 'relative',
                    paddingLeft: 28,
                    paddingBottom: idx === b.events.length - 1 ? 0 : 14,
                    borderLeft: idx === b.events.length - 1
                      ? 'none'
                      : '2px solid #EEF4FF',
                    marginLeft: 6,
                  }}
                >
                  {/* 节点圆点 */}
                  <span
                    style={{
                      position: 'absolute',
                      left: -7,
                      top: 8,
                      width: 12,
                      height: 12,
                      borderRadius: '50%',
                      background: '#155EEF',
                      border: '2px solid #ffffff',
                      boxShadow: '0 0 0 2px #EEF4FF',
                    }}
                  />
                  {/* 时间标签 */}
                  <Text
                    style={{
                      fontSize: 12,
                      color: '#155EEF',
                      fontWeight: 600,
                      letterSpacing: 0.3,
                    }}
                  >
                    {fmtEventTime(ev, b.key)}
                  </Text>
                  {/* 事件卡片 */}
                  <div
                    style={{
                      marginTop: 4,
                      background: '#ffffff',
                      border: '1px solid #eef0f4',
                      borderRadius: 10,
                      padding: '10px 14px',
                      transition:
                        'border-color 0.18s, box-shadow 0.18s, transform 0.18s',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.borderColor = '#155EEF'
                      e.currentTarget.style.boxShadow =
                        '0 6px 14px -10px rgba(21, 94, 239, 0.3)'
                      e.currentTarget.style.transform = 'translateX(2px)'
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.borderColor = '#eef0f4'
                      e.currentTarget.style.boxShadow = ''
                      e.currentTarget.style.transform = ''
                    }}
                  >
                    <Text
                      strong
                      style={{
                        fontSize: 14.5,
                        color: '#171719',
                        display: 'block',
                        marginBottom: ev.description || ev.participants.length ? 4 : 0,
                      }}
                    >
                      {ev.title}
                    </Text>
                    {ev.description && (
                      <Paragraph
                        type="secondary"
                        style={{
                          margin: 0,
                          fontSize: 13,
                          lineHeight: 1.6,
                          color: '#667085',
                        }}
                        ellipsis={{ rows: 2, tooltip: ev.description }}
                      >
                        {ev.description}
                      </Paragraph>
                    )}
                    {ev.participants.length > 0 && (
                      <Space size={4} wrap style={{ marginTop: 8 }}>
                        {ev.participants.map((p) => (
                          <Tag
                            key={p.id}
                            style={{
                              margin: 0,
                              fontSize: 11.5,
                              padding: '0 8px',
                              background: '#f0f7ff',
                              color: '#155EEF',
                              border: '1px solid #dbe6ff',
                              borderRadius: 999,
                            }}
                          >
                            {p.name}
                          </Tag>
                        ))}
                      </Space>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </Space>
    </div>
  )
}
