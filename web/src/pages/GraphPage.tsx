import { useEffect, useMemo, useRef, useState } from 'react'
import { Button, Card, Empty, Space, Spin, Tag, Typography, message } from 'antd'
import { MergeCellsOutlined, ReloadOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import { memoryApi, type GraphData, type GraphNode } from '@/api/memories'

const { Text, Paragraph } = Typography

// 节点大类：颜色 + 形状 + 中文名。实体/事件默认显示，溯源层（陈述/片段/对话）默认隐藏，
// 点下方圆点筛选按钮即可点亮查看「这条记忆从哪来」。
const KIND_ORDER = ['Entity', 'Event', 'Statement', 'Chunk', 'Dialogue'] as const
type Kind = (typeof KIND_ORDER)[number]
const KIND_META: Record<string, { label: string; color: string; symbol: string }> = {
  Entity: { label: '实体', color: '#155EEF', symbol: 'circle' },
  Event: { label: '事件', color: '#FF8A34', symbol: 'diamond' },
  Statement: { label: '陈述', color: '#52C41A', symbol: 'roundRect' },
  Chunk: { label: '片段', color: '#9254DE', symbol: 'rect' },
  Dialogue: { label: '对话', color: '#13A8A8', symbol: 'triangle' },
}
const REL_LABEL: Record<string, string> = {
  HAS_CHUNK: '包含片段',
  HAS_STATEMENT: '包含陈述',
  MENTIONS: '提及',
  RELATION: '关系',
  INVOLVES: '涉及',
}
const DEFAULT_KINDS: Kind[] = ['Entity', 'Event', 'Statement', 'Chunk', 'Dialogue']

interface EchartsParam {
  dataType?: string
  dataIndex?: number
}

export default function GraphPage() {
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<GraphData | null>(null)
  const [selected, setSelected] = useState<GraphNode | null>(null)
  const [merging, setMerging] = useState(false)
  // 当前显示的节点大类（默认只显示实体 + 事件，避免溯源层一次性全画导致卡顿）
  const [visibleKinds, setVisibleKinds] = useState<Set<string>>(() => new Set(DEFAULT_KINDS))
  // 容器实际高度（百分比高度在 minHeight 撑起的父级下会算成 0，必须用像素值喂给 ECharts）
  const wrapRef = useRef<HTMLDivElement>(null)
  const [chartH, setChartH] = useState(560)

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const update = () => setChartH(el.clientHeight || 560)
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [data])

  const load = (showLoading = true) => {
    if (showLoading) setLoading(true)
    setSelected(null)
    memoryApi
      .graph()
      .then(({ data }) => setData(data))
      .catch((e) => message.error((e as Error).message))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const onMergeDuplicates = async () => {
    setMerging(true)
    try {
      const { data } = await memoryApi.mergeDuplicates()
      message.success(`已合并 ${data.removed} 个重复实体`)
      load()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setMerging(false)
    }
  }

  const kindOf = (n: GraphNode): Kind =>
    n.kind && KIND_META[n.kind] ? (n.kind as Kind) : 'Entity'

  // 出现过的节点大类（用于筛选按钮 + 各类计数）
  const presentKinds = useMemo<Kind[]>(() => {
    if (!data) return []
    const counts = new Map<Kind, number>()
    data.nodes.forEach((n) => {
      const k = kindOf(n)
      counts.set(k, (counts.get(k) ?? 0) + 1)
    })
    return KIND_ORDER.filter((k) => counts.has(k))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  const kindCount = useMemo(() => {
    const m = new Map<Kind, number>()
    data?.nodes.forEach((n) => {
      const k = kindOf(n)
      m.set(k, (m.get(k) ?? 0) + 1)
    })
    return m
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  const toggleKind = (k: Kind) =>
    setVisibleKinds((prev) => {
      const next = new Set(prev)
      if (next.has(k)) next.delete(k)
      else next.add(k)
      return next
    })

  // 只把「可见大类」的节点和两端都可见的边喂给 ECharts（force 只算可见节点，流畅且必显示）
  const { option, visibleNodes } = useMemo(() => {
    if (!data || data.nodes.length === 0) return { option: null, visibleNodes: [] as GraphNode[] }

    // 全量连接度（节点大小用，反映真实重要度）
    const degree = new Map<string, number>()
    data.nodes.forEach((n) => degree.set(n.id, 0))
    data.edges.forEach((e) => {
      degree.set(e.source, (degree.get(e.source) ?? 0) + 1)
      degree.set(e.target, (degree.get(e.target) ?? 0) + 1)
    })
    const maxDeg = Math.max(1, ...Array.from(degree.values()))

    const vis = data.nodes.filter((n) => visibleKinds.has(kindOf(n)))
    const visIds = new Set(vis.map((n) => n.id))
    const idToIdx = new Map<string, number>()
    vis.forEach((n, i) => idToIdx.set(n.id, i))

    // 分类（颜色），按固定顺序取所有出现的大类
    const cats = presentKinds.map((k) => ({
      name: KIND_META[k].label,
      itemStyle: { color: KIND_META[k].color },
    }))
    const catIndex = new Map<Kind, number>()
    presentKinds.forEach((k, i) => catIndex.set(k, i))

    const nodes = vis.map((n) => {
      const kind = kindOf(n)
      const deg = degree.get(n.id) ?? 0
      const imp = typeof n.importance === 'number' ? n.importance : 0.5
      let size = 13
      if (kind === 'Entity') {
        size = Math.min(56, Math.max(16, Math.round(18 + (deg / maxDeg) * 30 + imp * 8)))
      } else if (kind === 'Event') {
        size = 24
      }
      return {
        name: n.name,
        symbol: KIND_META[kind].symbol,
        symbolSize: size,
        category: catIndex.get(kind),
        value: deg,
      }
    })

    const visibleEdges = data.edges.filter(
      (e) => visIds.has(e.source) && visIds.has(e.target),
    )
    const links = visibleEdges.map((e) => {
      const isRelation = e.rel === 'RELATION'
      return {
        source: idToIdx.get(e.source)!,
        target: idToIdx.get(e.target)!,
        lineStyle: isRelation
          ? { color: '#C9CDD4', width: 1.2, opacity: 0.75 }
          : { color: '#E5E6EB', width: 1, type: 'dashed', opacity: 0.6 },
      }
    })

    const repulsion = vis.length > 80 ? 320 : vis.length > 40 ? 240 : 180

    const opt = {
      tooltip: {
        confine: true,
        formatter: (p: EchartsParam) => {
          if (p.dataType === 'edge' && p.dataIndex !== undefined) {
            const e = visibleEdges[p.dataIndex]
            if (!e) return ''
            return e.predicate_surface || e.predicate || REL_LABEL[e.rel ?? ''] || ''
          }
          if (p.dataType === 'node' && p.dataIndex !== undefined) {
            const n = vis[p.dataIndex]
            if (!n) return ''
            const kindLabel = KIND_META[n.kind ?? 'Entity']?.label ?? '实体'
            const facts = (n.core_facts ?? [])
              .slice(0, 3)
              .map((f) => `• ${f}`)
              .join('<br/>')
            return `<b>${n.name}</b> <span style="color:#98A2B3">${
              n.type || kindLabel
            }</span>${facts ? `<br/>${facts}` : ''}`
          }
          return ''
        },
      },
      series: [
        {
          type: 'graph',
          layout: 'force',
          roam: true,
          draggable: true,
          categories: cats,
          data: nodes,
          links,
          edgeSymbol: ['none', 'arrow'],
          edgeSymbolSize: 6,
          force: {
            repulsion,
            edgeLength: [70, 160],
            gravity: 0.05,
            friction: 0.6,
          },
          label: { show: true, position: 'right', fontSize: 11, color: '#1D2129' },
          labelLayout: { hideOverlap: true },
          emphasis: {
            focus: 'adjacency',
            label: { show: true, fontWeight: 'bold' },
            lineStyle: { width: 2.5, color: '#155EEF', opacity: 1 },
          },
        },
      ],
    }
    return { option: opt, visibleNodes: vis }
  }, [data, visibleKinds, presentKinds])

  const onEvents = {
    click: (p: EchartsParam) => {
      if (p.dataType === 'node' && p.dataIndex !== undefined) {
        const n = visibleNodes[p.dataIndex]
        if (n && (n.kind === 'Entity' || !n.kind)) setSelected(n)
      }
    },
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <Card
        title="知识图谱"
        extra={
          <Space>
            <Button icon={<MergeCellsOutlined />} loading={merging} onClick={onMergeDuplicates}>
              合并重复
            </Button>
            <Button icon={<ReloadOutlined />} onClick={() => load()} disabled={loading}>
              刷新
            </Button>
          </Space>
        }
        styles={{ body: { padding: 0, height: 'calc(100% - 57px)' } }}
        style={{ flex: 1, display: 'flex', flexDirection: 'column' }}
      >
        <div ref={wrapRef} style={{ position: 'relative', height: '100%', minHeight: '32rem' }}>
          {loading ? (
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
              <Spin />
            </div>
          ) : !data || data.nodes.length === 0 ? (
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
              <Empty description="还没有记忆实体，先去主动记住或对话萃取一些记忆" />
            </div>
          ) : (
            <>
              {option && (
                <ReactECharts
                  key={Array.from(visibleKinds).sort().join(',')}
                  option={option}
                  notMerge
                  style={{ width: '100%', height: chartH }}
                  onEvents={onEvents}
                />
              )}

              {/* 类型筛选圆点：点击显隐对应大类 */}
              <div
                style={{
                  position: 'absolute',
                  bottom: 14,
                  left: '50%',
                  transform: 'translateX(-50%)',
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: 8,
                  background: 'rgba(255,255,255,0.92)',
                  borderRadius: 20,
                  padding: '6px 12px',
                  boxShadow: '0 2px 10px rgba(0,0,0,0.08)',
                }}
              >
                {presentKinds.map((k) => {
                  const on = visibleKinds.has(k)
                  const meta = KIND_META[k]
                  return (
                    <span
                      key={k}
                      onClick={() => toggleKind(k)}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 5,
                        fontSize: 12,
                        cursor: 'pointer',
                        color: on ? '#1D2129' : '#BFBFBF',
                        userSelect: 'none',
                      }}
                    >
                      <span
                        style={{
                          width: 10,
                          height: 10,
                          borderRadius: '50%',
                          background: on ? meta.color : '#D9D9D9',
                          display: 'inline-block',
                        }}
                      />
                      {meta.label}
                      <span style={{ color: '#98A2B3' }}>{kindCount.get(k) ?? 0}</span>
                    </span>
                  )
                })}
              </div>

              {selected && (
                <div
                  style={{
                    position: 'absolute',
                    top: 16,
                    right: 16,
                    width: '18rem',
                    maxWidth: '80%',
                    background: '#fff',
                    borderRadius: 12,
                    boxShadow: '0 4px 16px rgba(0,0,0,0.1)',
                    padding: 16,
                  }}
                >
                  <Text strong style={{ fontSize: 16 }}>
                    {selected.name}
                  </Text>
                  <div style={{ margin: '8px 0', display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    <Tag color="blue">{selected.type}</Tag>
                    {selected.memory_layer === 'long_term' ? (
                      <Tag color="gold">长期记忆</Tag>
                    ) : (
                      <Tag>短期记忆</Tag>
                    )}
                    {typeof selected.importance === 'number' && (
                      <Tag color="green">重要度 {Math.round(selected.importance * 100)}</Tag>
                    )}
                  </div>
                  {selected.description && (
                    <Paragraph type="secondary" style={{ fontSize: 13, marginBottom: 8 }}>
                      {selected.description}
                    </Paragraph>
                  )}
                  {selected.traits && selected.traits.length > 0 && (
                    <div style={{ marginBottom: 8 }}>
                      {selected.traits.map((t) => (
                        <Tag key={t} color="purple" style={{ fontSize: 12 }}>
                          {t}
                        </Tag>
                      ))}
                    </div>
                  )}
                  {selected.core_facts && selected.core_facts.length > 0 && (
                    <div style={{ marginBottom: 8 }}>
                      {selected.core_facts.slice(0, 5).map((f, i) => (
                        <div key={i} style={{ fontSize: 12.5, color: '#155EEF', lineHeight: 1.7 }}>
                          ✦ {f}
                        </div>
                      ))}
                    </div>
                  )}
                  <div style={{ fontSize: 12, color: '#98A2B3' }}>
                    被提及 {selected.mention_count ?? 1} 次 · 被检索 {selected.access_count ?? 0} 次
                  </div>
                  <Button
                    size="small"
                    type="text"
                    style={{ marginTop: 8, paddingLeft: 0, color: '#98A2B3' }}
                    onClick={() => setSelected(null)}
                  >
                    关闭
                  </Button>
                </div>
              )}

              <div
                style={{
                  position: 'absolute',
                  left: 16,
                  top: 16,
                  background: 'rgba(255,255,255,0.92)',
                  borderRadius: 8,
                  padding: '6px 10px',
                  fontSize: 12,
                  color: '#667085',
                  pointerEvents: 'none',
                  maxWidth: '60%',
                }}
              >
                共 {data.nodes.length} 节点 · {data.edges.length} 关系，当前显示{' '}
                {visibleNodes.length} 个
                <br />
                点下方圆点可隐藏某类型 · 大小=连接数 · 滚轮缩放、拖拽 · 点实体看详情
              </div>
            </>
          )}
        </div>
      </Card>
    </div>
  )
}
