import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button, Card, Empty, Input, Space, Spin, Tag, Typography, message } from 'antd'
import {
  AimOutlined,
  MergeCellsOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d'
import { memoryApi, type GraphData, type GraphNode } from '@/api/memories'

const { Text, Paragraph } = Typography

// 节点大类：颜色 + 中文名。实体/事件默认显示，溯源层（陈述/片段/对话）默认隐藏。
const KIND_ORDER = ['Entity', 'Event', 'Statement', 'Chunk', 'Dialogue'] as const
type Kind = (typeof KIND_ORDER)[number]
const KIND_META: Record<string, { label: string; color: string }> = {
  Entity: { label: '实体', color: '#155EEF' },
  Event: { label: '事件', color: '#FF8A34' },
  Statement: { label: '陈述', color: '#52C41A' },
  Chunk: { label: '片段', color: '#9254DE' },
  Dialogue: { label: '对话', color: '#13A8A8' },
}
const REL_LABEL: Record<string, string> = {
  HAS_CHUNK: '包含片段',
  HAS_STATEMENT: '包含陈述',
  MENTIONS: '提及',
  RELATION: '关系',
  INVOLVES: '涉及',
}
const DEFAULT_KINDS: Kind[] = ['Entity', 'Event']
const SEED_NEIGHBORS = 1 // 初始焦点展开的跳数

// react-force-graph 会就地给节点对象补 x/y/vx/vy/fx/fy，故用可变对象
interface FGNode extends GraphNode {
  deg: number
  x?: number
  y?: number
  fx?: number
  fy?: number
}
interface FGLink {
  source: string | FGNode
  target: string | FGNode
  rel?: string
  predicate?: string
  predicate_surface?: string
}

const lid = (x: string | FGNode): string => (typeof x === 'object' ? x.id : x)

function kindOf(n: GraphNode): Kind {
  return n.kind && KIND_META[n.kind] ? (n.kind as Kind) : 'Entity'
}

function useIsMobile() {
  const [m, setM] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(max-width: 768px)').matches,
  )
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 768px)')
    const h = (e: MediaQueryListEvent) => setM(e.matches)
    mq.addEventListener('change', h)
    return () => mq.removeEventListener('change', h)
  }, [])
  return m
}

export default function GraphPage() {
  const isMobile = useIsMobile()
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<GraphData | null>(null)
  const [selected, setSelected] = useState<GraphNode | null>(null)
  const [merging, setMerging] = useState(false)
  const [search, setSearch] = useState('')
  const [visibleKinds, setVisibleKinds] = useState<Set<string>>(() => new Set(DEFAULT_KINDS))

  // 当前“已展开”的节点集合（探索式：从焦点出发，点哪展开哪），用 id 集合驱动
  const [shownIds, setShownIds] = useState<Set<string>>(() => new Set())
  // 高亮（hover 聚焦邻居）
  const highlightNodes = useRef<Set<string>>(new Set())
  const highlightLinks = useRef<Set<FGLink>>(new Set())
  const [, forceTick] = useState(0)

  const fgRef = useRef<ForceGraphMethods<FGNode, FGLink> | undefined>(undefined)
  const wrapRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: 800, h: 560 })

  // 全量数据派生：节点表、邻接表、度数、持久可变节点对象（保留物理位置）
  const store = useMemo(() => {
    const nodeMap = new Map<string, GraphNode>()
    const adj = new Map<string, Set<string>>()
    const degree = new Map<string, number>()
    const fgNodes = new Map<string, FGNode>()
    if (data) {
      data.nodes.forEach((n) => {
        nodeMap.set(n.id, n)
        adj.set(n.id, new Set())
        degree.set(n.id, 0)
      })
      data.edges.forEach((e) => {
        if (!nodeMap.has(e.source) || !nodeMap.has(e.target)) return
        adj.get(e.source)!.add(e.target)
        adj.get(e.target)!.add(e.source)
        degree.set(e.source, (degree.get(e.source) ?? 0) + 1)
        degree.set(e.target, (degree.get(e.target) ?? 0) + 1)
      })
      data.nodes.forEach((n) =>
        fgNodes.set(n.id, { ...n, deg: degree.get(n.id) ?? 0 }),
      )
    }
    return { nodeMap, adj, degree, fgNodes }
  }, [data])

  // 容器尺寸自适应
  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const update = () =>
      setSize({ w: el.clientWidth || 800, h: el.clientHeight || 560 })
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [data])

  const load = useCallback((showLoading = true) => {
    if (showLoading) setLoading(true)
    setSelected(null)
    memoryApi
      .graph()
      .then(({ data }) => setData(data))
      .catch((e) => message.error((e as Error).message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // 数据到位后选种子（含「用户/我」优先，否则度数最高的实体）+ 展开一跳作为初始焦点
  useEffect(() => {
    if (!data || data.nodes.length === 0) {
      setShownIds(new Set())
      return
    }
    const entities = data.nodes.filter((n) => kindOf(n) === 'Entity')
    const pool = entities.length ? entities : data.nodes
    const seed =
      pool.find((n) => /用户|^我$|本人|自己/.test(n.name)) ??
      pool.reduce((a, b) =>
        (store.degree.get(b.id) ?? 0) > (store.degree.get(a.id) ?? 0) ? b : a,
      )
    const ids = new Set<string>([seed.id])
    let frontier = [seed.id]
    for (let hop = 0; hop < SEED_NEIGHBORS; hop++) {
      const next: string[] = []
      frontier.forEach((id) =>
        store.adj.get(id)?.forEach((nb) => {
          if (!ids.has(nb)) {
            ids.add(nb)
            next.push(nb)
          }
        }),
      )
      frontier = next
    }
    setShownIds(ids)
    // 居中
    setTimeout(() => fgRef.current?.zoomToFit(500, 60), 400)
  }, [data, store])

  const expand = useCallback(
    (id: string) => {
      setShownIds((prev) => {
        const next = new Set(prev)
        next.add(id)
        store.adj.get(id)?.forEach((nb) => next.add(nb))
        return next
      })
    },
    [store],
  )

  // 喂给力导图的数据：复用 store.fgNodes 持久对象引用（保留位置，避免每次重排）
  const graphData = useMemo(() => {
    const nodes: FGNode[] = []
    for (const id of shownIds) {
      const fn = store.fgNodes.get(id)
      if (fn && visibleKinds.has(kindOf(fn))) nodes.push(fn)
    }
    const visIds = new Set(nodes.map((n) => n.id))
    const links: FGLink[] = []
    data?.edges.forEach((e) => {
      if (visIds.has(e.source) && visIds.has(e.target)) {
        links.push({
          source: e.source,
          target: e.target,
          rel: e.rel,
          predicate: e.predicate,
          predicate_surface: e.predicate_surface,
        })
      }
    })
    return { nodes, links }
  }, [shownIds, visibleKinds, store, data])

  const maxDeg = useMemo(
    () => Math.max(1, ...Array.from(store.degree.values())),
    [store],
  )

  const nodeRadius = useCallback(
    (n: FGNode) => {
      const k = isMobile ? 1.5 : 1 // 手机端整体放大，便于点按
      const kind = kindOf(n)
      if (kind === 'Entity') {
        const imp = typeof n.importance === 'number' ? n.importance : 0.5
        return (Math.min(10, Math.max(3, 3 + (n.deg / maxDeg) * 6 + imp * 1.5))) * k
      }
      if (kind === 'Event') return 4.5 * k
      return 3.5 * k
    },
    [maxDeg, isMobile],
  )

  // 配置力的强度：加大斥力 + 拉长连线，让节点散开不重叠
  useEffect(() => {
    const fg = fgRef.current
    if (!fg) return
    const n = graphData.nodes.length
    const charge = n > 60 ? -420 : n > 25 ? -320 : -240
    fg.d3Force('charge')?.strength(charge)
    fg.d3Force('link')?.distance(70)
    fg.d3ReheatSimulation()
  }, [graphData])

  // hover 聚焦：高亮邻居 + 关联边，其余淡化
  const onNodeHover = useCallback(
    (node: FGNode | null) => {
      const hn = highlightNodes.current
      const hl = highlightLinks.current
      hn.clear()
      hl.clear()
      if (node) {
        hn.add(node.id)
        graphData.links.forEach((l) => {
          if (lid(l.source) === node.id || lid(l.target) === node.id) {
            hl.add(l)
            hn.add(lid(l.source))
            hn.add(lid(l.target))
          }
        })
      }
      forceTick((t) => t + 1)
    },
    [graphData],
  )

  const onNodeClick = useCallback(
    (node: FGNode) => {
      // 只展开关联 + 出详情，不移动/居中视图（避免每次点击图都跳）
      expand(node.id)
      if (kindOf(node) === 'Entity') setSelected(node)
    },
    [expand],
  )

  const onNodeDragEnd = useCallback((node: FGNode) => {
    // 拖完固定该节点（pin），方便手动整理布局
    node.fx = node.x
    node.fy = node.y
  }, [])

  const doSearch = useCallback(
    (q: string) => {
      const kw = q.trim()
      if (!kw || !data) return
      const hit =
        store.fgNodes.get(kw) ??
        Array.from(store.fgNodes.values()).find((n) =>
          n.name.toLowerCase().includes(kw.toLowerCase()),
        )
      if (!hit) {
        message.info('没找到匹配的实体')
        return
      }
      // 把命中点设为新焦点（它+一跳邻居），并居中
      const ids = new Set<string>([hit.id])
      store.adj.get(hit.id)?.forEach((nb) => ids.add(nb))
      setShownIds((prev) => new Set([...prev, ...ids]))
      setSelected(store.nodeMap.get(hit.id) ?? null)
      setTimeout(() => {
        if (hit.x != null && hit.y != null) fgRef.current?.centerAt(hit.x, hit.y, 600)
        fgRef.current?.zoom(2.2, 600)
      }, 300)
    },
    [data, store],
  )

  const presentKinds = useMemo<Kind[]>(() => {
    if (!data) return []
    const set = new Set<Kind>()
    data.nodes.forEach((n) => set.add(kindOf(n)))
    return KIND_ORDER.filter((k) => set.has(k))
  }, [data])

  const kindCount = useMemo(() => {
    const m = new Map<Kind, number>()
    data?.nodes.forEach((n) => m.set(kindOf(n), (m.get(kindOf(n)) ?? 0) + 1))
    return m
  }, [data])

  const toggleKind = (k: Kind) =>
    setVisibleKinds((prev) => {
      const next = new Set(prev)
      if (next.has(k)) next.delete(k)
      else next.add(k)
      return next
    })

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

  const resetView = () => {
    // 解除所有 pin，回到焦点视图
    store.fgNodes.forEach((n) => {
      n.fx = undefined
      n.fy = undefined
    })
    load()
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <Card
        title={isMobile ? undefined : '知识图谱'}
        extra={
          <Space wrap size={isMobile ? 4 : 8} style={isMobile ? { width: '100%' } : undefined}>
            <Input.Search
              placeholder="搜索实体定位"
              allowClear
              size="small"
              style={{ width: isMobile ? 130 : 180 }}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onSearch={doSearch}
            />
            <Button
              size="small"
              icon={<AimOutlined />}
              onClick={() => fgRef.current?.zoomToFit(500, 60)}
            >
              {isMobile ? '' : '居中'}
            </Button>
            <Button
              size="small"
              icon={<MergeCellsOutlined />}
              loading={merging}
              onClick={onMergeDuplicates}
            >
              {isMobile ? '' : '合并重复'}
            </Button>
            <Button
              size="small"
              icon={<ReloadOutlined />}
              onClick={resetView}
              disabled={loading}
            >
              {isMobile ? '' : '重置视图'}
            </Button>
          </Space>
        }
        styles={{ body: { padding: 0, height: isMobile ? 'calc(100% - 52px)' : 'calc(100% - 57px)' } }}
        style={{ flex: 1, display: 'flex', flexDirection: 'column' }}
      >
        <div
          ref={wrapRef}
          style={{ position: 'relative', height: '100%', minHeight: '32rem', overflow: 'hidden' }}
        >
          {loading ? (
            <div style={center}>
              <Spin />
            </div>
          ) : !data || data.nodes.length === 0 ? (
            <div style={center}>
              <Empty description="还没有记忆实体，先去主动记住或对话萃取一些记忆" />
            </div>
          ) : (
            <>
              <ForceGraph2D
                ref={fgRef}
                graphData={graphData}
                width={size.w}
                height={size.h}
                nodeId="id"
                cooldownTicks={120}
                d3VelocityDecay={0.3}
                linkColor={(l) =>
                  highlightLinks.current.has(l as FGLink)
                    ? '#155EEF'
                    : (l as FGLink).rel === 'RELATION'
                      ? 'rgba(150,160,175,0.55)'
                      : 'rgba(200,205,215,0.4)'
                }
                linkWidth={(l) => (highlightLinks.current.has(l as FGLink) ? 2.5 : 1)}
                linkDirectionalArrowLength={(l) =>
                  (l as FGLink).rel === 'RELATION' ? 3.5 : 0
                }
                linkDirectionalArrowRelPos={1}
                linkLabel={(l) => {
                  const e = l as FGLink
                  return e.predicate_surface || e.predicate || REL_LABEL[e.rel ?? ''] || ''
                }}
                onNodeHover={(n) => onNodeHover(n as FGNode | null)}
                onNodeClick={(n) => onNodeClick(n as FGNode)}
                onNodeDragEnd={(n) => onNodeDragEnd(n as FGNode)}
                onBackgroundClick={() => setSelected(null)}
                nodeCanvasObject={(node, ctx, globalScale) => {
                  const n = node as FGNode
                  const r = nodeRadius(n)
                  const color = KIND_META[kindOf(n)].color
                  const dim =
                    highlightNodes.current.size > 0 && !highlightNodes.current.has(n.id)
                  ctx.globalAlpha = dim ? 0.18 : 1
                  // 节点圆
                  ctx.beginPath()
                  ctx.arc(n.x!, n.y!, r, 0, 2 * Math.PI)
                  ctx.fillStyle = color
                  ctx.fill()
                  if (selected?.id === n.id) {
                    ctx.lineWidth = 2 / globalScale
                    ctx.strokeStyle = '#155EEF'
                    ctx.stroke()
                  }
                  // 标签：缩得太小不画，避免糊成一团
                  if (globalScale > 0.7 || r > 9) {
                    const label = n.name.length > 10 ? n.name.slice(0, 10) + '…' : n.name
                    const fs = Math.max(3, 11 / globalScale)
                    ctx.font = `${fs}px -apple-system, "PingFang SC", sans-serif`
                    ctx.textAlign = 'center'
                    ctx.textBaseline = 'top'
                    ctx.fillStyle = dim ? 'rgba(29,33,41,0.25)' : '#1D2129'
                    ctx.fillText(label, n.x!, n.y! + r + 1)
                  }
                  ctx.globalAlpha = 1
                }}
                nodePointerAreaPaint={(node, color, ctx) => {
                  const n = node as FGNode
                  ctx.fillStyle = color
                  ctx.beginPath()
                  // 手机端加大点按热区，手指更好点中
                  ctx.arc(n.x!, n.y!, nodeRadius(n) + (isMobile ? 6 : 2), 0, 2 * Math.PI)
                  ctx.fill()
                }}
              />

              {/* 类型筛选圆点 */}
              <div style={filterBar}>
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
                <div style={isMobile ? detailSheetMobile : detailPanel}>
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

              <div style={isMobile ? { ...hintBox, ...hintBoxMobile } : hintBox}>
                共 {data.nodes.length} 节点 · {data.edges.length} 关系，当前展开{' '}
                {graphData.nodes.length} 个
                <br />
                {isMobile
                  ? '点节点展开关联 · 双指缩放 · 拖动整理 · 下方筛类型'
                  : '点节点展开它的关联 · 拖动可固定 · 滚轮缩放 · 搜索定位 · 下方圆点筛类型'}
              </div>
            </>
          )}
        </div>
      </Card>
    </div>
  )
}

const center: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'center',
  alignItems: 'center',
  height: '100%',
}

const filterBar: React.CSSProperties = {
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
}

const detailPanel: React.CSSProperties = {
  position: 'absolute',
  top: 16,
  right: 16,
  width: '18rem',
  maxWidth: '80%',
  background: '#fff',
  borderRadius: 12,
  boxShadow: '0 4px 16px rgba(0,0,0,0.1)',
  padding: 16,
}

// 手机端：详情改为顶部抽屉式卡片（不挡底部的类型筛选条）
const detailSheetMobile: React.CSSProperties = {
  position: 'absolute',
  left: 0,
  right: 0,
  top: 0,
  background: '#fff',
  borderRadius: '0 0 16px 16px',
  boxShadow: '0 6px 20px rgba(0,0,0,0.12)',
  padding: 16,
  maxHeight: '52%',
  overflowY: 'auto',
  zIndex: 5,
}

const hintBox: React.CSSProperties = {
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
}

// 手机端提示：更窄、字更小、贴边，少占空间
const hintBoxMobile: React.CSSProperties = {
  left: 8,
  top: 8,
  padding: '5px 8px',
  fontSize: 11,
  maxWidth: '92%',
  lineHeight: 1.5,
}
