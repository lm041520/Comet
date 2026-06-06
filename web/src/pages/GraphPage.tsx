import { useEffect, useMemo, useRef, useState } from 'react'
import { Button, Card, Empty, Space, Spin, Tag, Typography, message } from 'antd'
import { MergeCellsOutlined, ReloadOutlined } from '@ant-design/icons'
import { Graph } from '@antv/x6'
import { memoryApi, type GraphData, type GraphNode } from '@/api/memories'

const { Text, Paragraph } = Typography

// 社区调色板：按社区 id 稳定取色；无社区按实体类型回退
const PALETTE = [
  '#155EEF', '#369F21', '#FF5D34', '#9254DE', '#13A8A8',
  '#FA8C16', '#EB2F96', '#2F54EB', '#52C41A', '#FAAD14',
  '#722ED1', '#08979C', '#D4380D', '#C41D7F', '#1677FF',
]

function colorForKey(key: string, table: Map<string, string>): string {
  if (!table.has(key)) {
    table.set(key, PALETTE[table.size % PALETTE.length])
  }
  return table.get(key)!
}

// 力导向布局：相连节点吸引、所有节点排斥，迭代后形成自然的簇状分布（不再排成圆圈）。
// 系数调到中等密度——既不挤成一团，也不散得太开。
function forceLayout(
  nodes: GraphNode[],
  edges: { source: string; target: string }[],
  width: number,
  height: number,
): Map<string, { x: number; y: number }> {
  const pos = new Map<string, { x: number; y: number }>()
  const cx = width / 2
  const cy = height / 2
  const N = nodes.length

  // 初始：在中心附近小范围随机散布
  nodes.forEach((n) => {
    const a = Math.random() * 2 * Math.PI
    const r = Math.random() * Math.min(width, height) * 0.3
    pos.set(n.id, { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) })
  })
  if (N <= 1) return pos

  const k = Math.sqrt((width * height) / N) * 1.25 // 理想边长，越大越松
  const iterations = 320
  let temp = Math.min(width, height) / 5

  for (let it = 0; it < iterations; it++) {
    const disp = new Map<string, { x: number; y: number }>()
    nodes.forEach((n) => disp.set(n.id, { x: 0, y: 0 }))

    // 排斥力
    for (let i = 0; i < N; i++) {
      const a = pos.get(nodes[i].id)!
      const da = disp.get(nodes[i].id)!
      for (let j = i + 1; j < N; j++) {
        const b = pos.get(nodes[j].id)!
        let dx = a.x - b.x
        let dy = a.y - b.y
        let dist = Math.sqrt(dx * dx + dy * dy)
        if (dist < 0.01) {
          dx = Math.random() - 0.5
          dy = Math.random() - 0.5
          dist = 0.01
        }
        const f = (k * k) / dist
        const fx = (dx / dist) * f
        const fy = (dy / dist) * f
        da.x += fx
        da.y += fy
        const db = disp.get(nodes[j].id)!
        db.x -= fx
        db.y -= fy
      }
    }

    // 吸引力（相连节点）
    edges.forEach((e) => {
      const a = pos.get(e.source)
      const b = pos.get(e.target)
      if (!a || !b) return
      const dx = a.x - b.x
      const dy = a.y - b.y
      const dist = Math.sqrt(dx * dx + dy * dy) || 0.01
      const f = (dist * dist) / k
      const fx = (dx / dist) * f
      const fy = (dy / dist) * f
      disp.get(e.source)!.x -= fx
      disp.get(e.source)!.y -= fy
      disp.get(e.target)!.x += fx
      disp.get(e.target)!.y += fy
    })

    // 应用位移（限温）+ 轻微向心力，防止离群节点飘太远
    nodes.forEach((n) => {
      const d = disp.get(n.id)!
      const p = pos.get(n.id)!
      const dl = Math.sqrt(d.x * d.x + d.y * d.y) || 0.01
      p.x += (d.x / dl) * Math.min(dl, temp)
      p.y += (d.y / dl) * Math.min(dl, temp)
      p.x += (cx - p.x) * 0.008
      p.y += (cy - p.y) * 0.008
    })
    temp *= 0.97
  }
  return pos
}

export default function GraphPage() {
  const containerRef = useRef<HTMLDivElement>(null)
  const graphRef = useRef<Graph | null>(null)
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<GraphData | null>(null)
  const [selected, setSelected] = useState<GraphNode | null>(null)
  const [merging, setMerging] = useState(false)
  const adjRef = useRef<Map<string, Set<string>>>(new Map())

  const colorTable = useMemo(() => new Map<string, string>(), [])

  const reload = () => {
    setLoading(true)
    setSelected(null)
    memoryApi
      .graph()
      .then(({ data }) => setData(data))
      .catch((e) => message.error((e as Error).message))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    let mounted = true
    setLoading(true)
    memoryApi
      .graph()
      .then(({ data }) => {
        if (mounted) setData(data)
      })
      .catch((e) => message.error((e as Error).message))
      .finally(() => {
        if (mounted) setLoading(false)
      })
    return () => {
      mounted = false
    }
  }, [])

  const onMergeDuplicates = async () => {
    setMerging(true)
    try {
      const { data } = await memoryApi.mergeDuplicates()
      message.success(`已合并 ${data.removed} 个重复实体`)
      reload()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setMerging(false)
    }
  }

  useEffect(() => {
    if (!data || !containerRef.current) return
    if (data.nodes.length === 0) return

    const container = containerRef.current
    const width = container.clientWidth || 800
    const height = container.clientHeight || 600

    const graph = new Graph({
      container,
      width,
      height,
      background: { color: '#FAFAFA' },
      panning: true,
      mousewheel: { enabled: true, modifiers: [], minScale: 0.2, maxScale: 3 },
      interacting: { nodeMovable: true },
    })
    graphRef.current = graph

    const adj = new Map<string, Set<string>>()
    data.nodes.forEach((nd) => adj.set(nd.id, new Set()))
    data.edges.forEach((e) => {
      adj.get(e.source)?.add(e.target)
      adj.get(e.target)?.add(e.source)
    })
    adjRef.current = adj

    // 力导向布局：相关节点聚成簇，整体中等密度（不再排成圆圈）
    const pos = forceLayout(data.nodes, data.edges, width, height)

    data.nodes.forEach((node) => {
      const p = pos.get(node.id)!
      const key = node.community_id || `type:${node.type}`
      const color = colorForKey(key, colorTable)
      // 节点大小按重要度缩放（18~32px），名称显示在节点下方
      const importance = typeof node.importance === 'number' ? node.importance : 0.5
      const size = Math.round(18 + importance * 14)
      graph.addNode({
        id: node.id,
        x: p.x - size / 2,
        y: p.y - size / 2,
        width: size,
        height: size,
        shape: 'rect',
        label: node.name,
        attrs: {
          body: { fill: color, stroke: '#fff', strokeWidth: 2, rx: 6, ry: 6 },
          label: {
            text: node.name,
            fill: '#1D2129',
            fontSize: 12,
            fontWeight: 500,
            refX: '50%',
            refY: '130%',
            textAnchor: 'middle',
            textVerticalAnchor: 'top',
          },
        },
        data: node,
      })
    })

    data.edges.forEach((e) => {
      graph.addEdge({
        source: e.source,
        target: e.target,
        attrs: {
          line: {
            stroke: '#C0C4CC',
            strokeWidth: 1.2,
            targetMarker: { name: 'classic', size: 5 },
          },
        },
        labels: e.predicate
          ? [
              {
                attrs: {
                  label: { text: e.predicate, fontSize: 10, fill: '#8C8C8C' },
                  body: { fill: '#FAFAFA', stroke: 'none' },
                },
              },
            ]
          : [],
      })
    })

    graph.on('node:click', ({ node }) => {
      const nd = node.getData<GraphNode>()
      setSelected(nd)
      highlight(graph, node.id, adjRef.current)
    })
    graph.on('blank:click', () => {
      setSelected(null)
      resetHighlight(graph)
    })

    graph.zoomToFit({ padding: 40, maxScale: 1 })

    return () => {
      graph.dispose()
      graphRef.current = null
    }
  }, [data, colorTable])

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <Card
        title="知识图谱"
        extra={
          <Space>
            <Button icon={<MergeCellsOutlined />} loading={merging} onClick={onMergeDuplicates}>
              合并重复
            </Button>
            <Button icon={<ReloadOutlined />} onClick={reload} disabled={loading}>
              刷新
            </Button>
          </Space>
        }
        styles={{ body: { padding: 0, height: 'calc(100% - 57px)' } }}
        style={{ flex: 1, display: 'flex', flexDirection: 'column' }}
      >
        <div style={{ position: 'relative', height: '100%', minHeight: '32rem' }}>
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
              <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
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
                </div>
              )}
              <div
                style={{
                  position: 'absolute',
                  left: 16,
                  bottom: 16,
                  background: 'rgba(255,255,255,0.9)',
                  borderRadius: 8,
                  padding: '6px 10px',
                  fontSize: 12,
                  color: '#667085',
                }}
              >
                {data.nodes.length} 个实体 · {data.edges.length} 条关系 · 颜色区分主题社区 · 大小表示重要度
              </div>
            </>
          )}
        </div>
      </Card>
    </div>
  )
}

function highlight(graph: Graph, nodeId: string, adj: Map<string, Set<string>>) {
  const neighbors = adj.get(nodeId) || new Set<string>()
  graph.getNodes().forEach((node) => {
    const isActive = node.id === nodeId || neighbors.has(node.id)
    node.attr('body/opacity', isActive ? 1 : 0.2)
    node.attr('label/opacity', isActive ? 1 : 0.2)
  })
  graph.getEdges().forEach((edge) => {
    const s = edge.getSourceCellId()
    const t = edge.getTargetCellId()
    const isActive = s === nodeId || t === nodeId
    edge.attr('line/stroke', isActive ? '#155EEF' : '#E5E6EB')
    edge.attr('line/opacity', isActive ? 1 : 0.2)
  })
}

function resetHighlight(graph: Graph) {
  graph.getNodes().forEach((node) => {
    node.attr('body/opacity', 1)
    node.attr('label/opacity', 1)
  })
  graph.getEdges().forEach((edge) => {
    edge.attr('line/stroke', '#C0C4CC')
    edge.attr('line/opacity', 1)
  })
}
