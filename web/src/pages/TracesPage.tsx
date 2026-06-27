/**
 * Trace 列表 + 详情页(V0.0.5 ③ Agent 全链路可观测)
 *
 * 列表:近 N 天的 Agent 任务,按时间倒序,带筛选(task_type / status / 天数)
 * 详情:点开任一条 → 时间线 Gantt 视图(TraceTimeline 组件) + KPI 卡 + 关联 LoopRun 入口
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  App,
  Button,
  Card,
  Drawer,
  Empty,
  Segmented,
  Select,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import {
  ClockCircleOutlined,
  CloseCircleOutlined,
  DollarOutlined,
  LinkOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'

import {
  traceApi,
  type TraceDetail,
  type TraceListItem,
} from '@/api/traces'
import { dashboardApi, type LoopHealthData } from '@/api/dashboard'
import TraceNarrative from '@/components/trace/TraceNarrative'
import TraceTimeline from '@/components/trace/TraceTimeline'
import CostCard from '@/components/trace/CostCard'
import LoopHealthCard from '@/components/research/LoopHealthCard'

const { Text, Title, Paragraph } = Typography

function fmtMs(ms: number | null): string {
  if (ms == null) return '-'
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)}s`
  return `${(ms / 60_000).toFixed(1)}m`
}

function fmtCost(cny: number): string {
  if (cny === 0) return '-'
  if (cny < 0.01) return `¥${cny.toFixed(5)}`
  return `¥${cny.toFixed(4)}`
}

function fmtTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

const TASK_TYPE_LABELS: Record<string, string> = {
  research: '深度研究',
  chat: '对话',
  agent_task: '定时任务',
  verify: '审稿',
  repair: '修复',
}

const TASK_TYPE_COLORS: Record<string, string> = {
  research: 'purple',
  chat: 'blue',
  agent_task: 'orange',
  verify: 'cyan',
  repair: 'magenta',
}

export default function TracesPage() {
  const { message } = App.useApp()
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const initialTraceId = searchParams.get('trace_id')
  const initialTaskId = searchParams.get('task_id')

  // 手机端断点
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

  const [items, setItems] = useState<TraceListItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [days, setDays] = useState<number>(7)
  const [taskType, setTaskType] = useState<string | undefined>(undefined)
  const [status, setStatus] = useState<string | undefined>(undefined)

  const [detailOpen, setDetailOpen] = useState(false)
  const [detail, setDetail] = useState<TraceDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  // V0.0.5 ②:Loop 健康度(从首页迁过来,与执行轨迹在同一页聚合 Agent 运行视图)
  const [loopHealth, setLoopHealth] = useState<LoopHealthData | null>(null)
  useEffect(() => {
    let cancelled = false
    dashboardApi
      .loopHealth(30)
      .then(({ data }) => {
        if (!cancelled) setLoopHealth(data)
      })
      .catch(() => {
        if (!cancelled) setLoopHealth(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await traceApi.list({ days, task_type: taskType, status, limit: 50 })
      setItems(res.data.items)
      setTotal(res.data.total)
    } catch (e) {
      message.error((e as { message?: string })?.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [days, taskType, status, message])

  useEffect(() => {
    load()
  }, [load])

  const openDetail = useCallback(
    async (traceId: string) => {
      setDetailOpen(true)
      setDetail(null)
      setDetailLoading(true)
      // 路由同步,刷新可保留打开状态
      const params = new URLSearchParams(searchParams)
      params.set('trace_id', traceId)
      setSearchParams(params, { replace: true })
      try {
        const res = await traceApi.detail(traceId)
        setDetail(res.data)
      } catch (e) {
        message.error((e as { message?: string })?.message || '加载详情失败')
        setDetailOpen(false)
      } finally {
        setDetailLoading(false)
      }
    },
    [searchParams, setSearchParams, message],
  )

  // URL 带 trace_id 时,自动打开详情
  useEffect(() => {
    if (initialTraceId && !detail && !detailLoading) {
      openDetail(initialTraceId)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialTraceId])

  // URL 带 task_id 时,自动找该 task 的最新一条 trace 并打开
  useEffect(() => {
    if (!initialTraceId && initialTaskId) {
      ;(async () => {
        try {
          const res = await traceApi.list({ task_id: initialTaskId, limit: 1 })
          const first = res.data.items[0]
          if (first) {
            openDetail(first.trace_id)
          } else {
            message.info('该任务暂无执行轨迹记录')
          }
        } catch (e) {
          message.error((e as { message?: string })?.message || '查询轨迹失败')
        }
      })()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialTaskId])

  const closeDetail = () => {
    setDetailOpen(false)
    setDetail(null)
    const params = new URLSearchParams(searchParams)
    params.delete('trace_id')
    setSearchParams(params, { replace: true })
  }

  // 汇总卡:近 N 天总成本/总任务/失败率
  const summary = useMemo(() => {
    const totalCost = items.reduce((s, x) => s + (x.total_cost_cny || 0), 0)
    const failed = items.filter((x) => x.status === 'error').length
    const failRate = items.length > 0 ? failed / items.length : 0
    return {
      total_cost: totalCost,
      total_count: items.length,
      failed,
      fail_rate: failRate,
    }
  }, [items])

  return (
    <div className="fluid-page">
      {/* Agent 运行监控 ——— V0.0.5 从首页迁过来,与执行轨迹列表组成「Agent 运行视图」 */}
      <CostCard />
      {loopHealth && loopHealth.total > 0 && (
        <div style={{ marginBottom: 22 }}>
          <LoopHealthCard data={loopHealth} />
        </div>
      )}
      <Card title="🔍 执行轨迹" className="memory-card">
        {/* 顶部汇总条:紧凑单行(冗余的「近 N 天范围」并到筛选栏右侧,失败率仅当有失败时显示)*/}
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'baseline',
            gap: 18,
            padding: '12px 16px',
            background: 'linear-gradient(135deg, #f4f8ff 0%, #ffffff 70%)',
            border: '1px solid #dbe6ff',
            borderRadius: 12,
            marginBottom: 14,
          }}
        >
          <SummaryStat
            icon={<ThunderboltOutlined />}
            value={String(summary.total_count)}
            unit="条"
            label="任务"
            color="#155EEF"
          />
          <SummaryStat
            icon={<DollarOutlined />}
            value={fmtCost(summary.total_cost)}
            label="本筛选成本"
            color="#FAAD14"
          />
          {summary.failed > 0 && (
            <SummaryStat
              icon={<CloseCircleOutlined />}
              value={`${(summary.fail_rate * 100).toFixed(1)}%`}
              label={`失败 ${summary.failed} 条`}
              color="#FF7875"
            />
          )}
          <div style={{ flex: 1 }} />
          <Text type="secondary" style={{ fontSize: 12, color: '#98A2B3' }}>
            <ClockCircleOutlined /> 近 {days} 天 · 共 {total} 条
          </Text>
        </div>

        {/* 筛选栏 */}
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            gap: 12,
            padding: '12px 16px',
            background: '#ffffff',
            border: '1px solid #eef0f4',
            borderRadius: 12,
            marginBottom: 14,
          }}
        >
          <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>
            时间窗口
          </Text>
          <Segmented
            size="small"
            value={days}
            onChange={(v) => setDays(v as number)}
            options={[
              { label: '近 1 天', value: 1 },
              { label: '近 7 天', value: 7 },
              { label: '近 30 天', value: 30 },
            ]}
          />
          <div style={{ width: 1, height: 18, background: '#eef0f4' }} />
          <Select
            size="small"
            value={taskType}
            onChange={(v) => setTaskType(v || undefined)}
            placeholder="全部任务类型"
            allowClear
            style={{ width: 160 }}
            options={Object.entries(TASK_TYPE_LABELS).map(([k, v]) => ({
              label: v,
              value: k,
            }))}
          />
          <Segmented
            size="small"
            value={status || 'all'}
            onChange={(v) => setStatus(v === 'all' ? undefined : (v as string))}
            options={[
              { label: '全部', value: 'all' },
              { label: '✓ 成功', value: 'ok' },
              { label: '⚠ 失败', value: 'error' },
              { label: '⏳ 运行中', value: 'running' },
            ]}
          />
          <div style={{ flex: 1 }} />
          <Tooltip title="刷新">
            <Button
              size="small"
              type="text"
              icon={<ReloadOutlined />}
              onClick={load}
              loading={loading}
            />
          </Tooltip>
        </div>

        {/* 列表 */}
        {loading ? (
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Spin />
          </div>
        ) : items.length === 0 ? (
          <Empty
            description={
              <span style={{ color: '#475467' }}>
                当前筛选条件下没有执行记录。先去跑一份「深度研究」或开启一次对话试试吧
              </span>
            }
            style={{ padding: '40px 0' }}
          />
        ) : (
          <Space direction="vertical" size={6} style={{ width: '100%' }}>
            {items.map((it) => (
              <TraceRow
                key={it.trace_id}
                item={it}
                isMobile={isMobile}
                onOpen={() => openDetail(it.trace_id)}
              />
            ))}
          </Space>
        )}
      </Card>

      {/* 详情 Drawer */}
      <Drawer
        open={detailOpen}
        onClose={closeDetail}
        title={
          detail ? (
            <div style={{ minWidth: 0, width: '100%' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                <Tag color={TASK_TYPE_COLORS[detail.task_type] || 'default'} style={{ marginInlineEnd: 0 }}>
                  {TASK_TYPE_LABELS[detail.task_type] || detail.task_type}
                </Tag>
                {detail.status === 'error' && <Tag color="error">失败</Tag>}
                {detail.status === 'running' && <Tag color="processing">运行中</Tag>}
              </div>
              <div
                style={{
                  width: '100%',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  fontSize: isMobile ? 14 : 16,
                  fontWeight: 600,
                }}
                title={detail.task_name || ''}
              >
                {detail.task_name || `Trace ${detail.trace_id.slice(0, 8)}`}
              </div>
            </div>
          ) : (
            '执行轨迹'
          )
        }
        width={isMobile ? '100%' : Math.min(1080, window.innerWidth - 24)}
        height={isMobile ? '92vh' : undefined}
        placement={isMobile ? 'bottom' : 'right'}
        styles={
          isMobile
            ? {
                content: { borderTopLeftRadius: 16, borderTopRightRadius: 16 },
                body: { padding: '14px 14px 24px' },
              }
            : undefined
        }
        destroyOnHidden
      >
        {detailLoading ? (
          <div style={{ textAlign: 'center', padding: 60 }}>
            <Spin tip="加载详情中…" />
          </div>
        ) : detail ? (
          <TraceDetailView detail={detail} onGoToReport={(reportId) => navigate(`/research?report=${reportId}`)} />
        ) : null}
      </Drawer>
    </div>
  )
}

// ── 列表行(紧凑单行,表格风)──

function TraceRow({ item, onOpen, isMobile }: { item: TraceListItem; onOpen: () => void; isMobile: boolean }) {
  const failed = item.status === 'error'
  const running = item.status === 'running'
  const totalTokens = item.total_input_tokens + item.total_output_tokens
  // 状态点指示符替代 Tag,更紧凑
  const statusDot = failed ? '#FF4D4F' : running ? '#1677FF' : '#52C41A'
  return (
    <div
      onClick={onOpen}
      style={{
        display: 'grid',
        // 桌面:类型 | 任务名(主)| 时间 | 耗时 | tokens | 成本 | 状态点
        // 手机:类型 任务名 状态点(1 行)+ 时间·耗时·tokens·成本(2 行)
        gridTemplateColumns: isMobile
          ? '52px 1fr 16px'
          : '60px 1fr 88px 64px 80px 72px 20px',
        gridTemplateRows: isMobile ? 'auto auto' : 'auto',
        gap: isMobile ? '4px 10px' : '0 12px',
        alignItems: 'center',
        padding: '10px 14px',
        background: '#ffffff',
        border: '1px solid #eef0f4',
        borderRadius: 10,
        cursor: 'pointer',
        fontSize: 12.5,
        transition: 'border-color 0.15s, background 0.15s',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = '#dbe6ff'
        e.currentTarget.style.background = '#fafbff'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = '#eef0f4'
        e.currentTarget.style.background = '#ffffff'
      }}
    >
      {/* 列 1:任务类型胶囊(固定宽度居中,让后面任务名起点对齐)*/}
      <Tag
        color={TASK_TYPE_COLORS[item.task_type] || 'default'}
        style={{
          margin: 0,
          fontSize: 11,
          padding: '0 6px',
          lineHeight: '18px',
          width: '100%',
          textAlign: 'center',
          display: 'block',
        }}
      >
        {TASK_TYPE_LABELS[item.task_type] || item.task_type}
      </Tag>

      {/* 列 2:任务名(主信息)*/}
      <span
        style={{
          fontWeight: 600,
          color: '#171719',
          fontSize: isMobile ? 13.5 : 13,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          minWidth: 0,
        }}
        title={item.task_name || ''}
      >
        {item.task_name || `Trace ${item.trace_id.slice(0, 8)}…`}
      </span>

      {!isMobile && (
        <>
          {/* 列 3:时间 */}
          <span style={{ color: '#98A2B3', fontSize: 12, whiteSpace: 'nowrap' }}>
            {fmtTime(item.started_at)}
          </span>
          {/* 列 4:耗时 */}
          <span style={{ color: '#667085', fontSize: 12, whiteSpace: 'nowrap' }}>
            {fmtMs(item.duration_ms)}
          </span>
          {/* 列 5:tokens */}
          <span style={{ color: '#667085', fontSize: 12, whiteSpace: 'nowrap' }}>
            {totalTokens >= 1000 ? `${(totalTokens / 1000).toFixed(1)}k` : totalTokens} tokens
          </span>
          {/* 列 6:成本 */}
          <span style={{ color: '#FAAD14', fontSize: 12, fontWeight: 600, whiteSpace: 'nowrap', textAlign: 'right' }}>
            {fmtCost(item.total_cost_cny)}
          </span>
        </>
      )}

      {/* 列 7:状态点(失败大红 / 运行中蓝 / 成功小绿点)*/}
      <Tooltip title={failed ? '失败' : running ? '运行中' : '成功'}>
        <span
          style={{
            display: 'inline-block',
            width: failed || running ? 10 : 8,
            height: failed || running ? 10 : 8,
            borderRadius: '50%',
            background: statusDot,
            boxShadow: running ? '0 0 0 3px rgba(22, 119, 255, 0.18)' : 'none',
            animation: running ? 'pulse 1.6s ease-in-out infinite' : 'none',
            justifySelf: 'center',
          }}
        />
      </Tooltip>

      {/* 手机端第二行:时间·耗时·tokens·成本 */}
      {isMobile && (
        <span
          style={{
            gridColumn: '2 / 4',
            color: '#98A2B3',
            fontSize: 11.5,
            display: 'flex',
            gap: 12,
            flexWrap: 'wrap',
          }}
        >
          <span>{fmtTime(item.started_at)}</span>
          <span>{fmtMs(item.duration_ms)}</span>
          <span>{totalTokens >= 1000 ? `${(totalTokens / 1000).toFixed(1)}k` : totalTokens}t</span>
          <span style={{ color: '#FAAD14', fontWeight: 600 }}>{fmtCost(item.total_cost_cny)}</span>
        </span>
      )}
    </div>
  )
}

// ── 详情视图 ──

function TraceDetailView({
  detail,
  onGoToReport,
}: {
  detail: TraceDetail
  onGoToReport: (reportId: string) => void
}) {
  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {/* 顶部 KPI */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
          gap: 10,
        }}
      >
        <Kpi label="总耗时" value={fmtMs(detail.duration_ms)} color="#155EEF" />
        <Kpi label="总成本" value={fmtCost(detail.total_cost_cny)} color="#FAAD14" />
        <Kpi label="输入 tokens" value={detail.total_input_tokens.toLocaleString()} color="#667085" />
        <Kpi label="输出 tokens" value={detail.total_output_tokens.toLocaleString()} color="#667085" />
        {detail.total_cached_tokens > 0 && (
          <Kpi label="缓存命中" value={detail.total_cached_tokens.toLocaleString()} color="#369F21" />
        )}
        <Kpi label="Span 数" value={String(detail.spans.length)} color="#7C4DFF" />
      </div>

      {/* 关联资源:跳回研究报告 / 任务页 */}
      {detail.task_id && detail.task_type === 'research' && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '12px 14px',
            background: 'linear-gradient(135deg, #f4f1fe 0%, #ffffff 70%)',
            border: '1px solid #e3dbff',
            borderRadius: 10,
          }}
        >
          <Space size={8}>
            <LinkOutlined style={{ color: '#7C4DFF' }} />
            <Text strong style={{ fontSize: 13 }}>关联研究报告</Text>
            {detail.loop_run_id && (
              <Tag color="purple" style={{ margin: 0 }}>含 Verifier Loop</Tag>
            )}
          </Space>
          <Button
            type="link"
            size="small"
            onClick={() => detail.task_id && onGoToReport(detail.task_id)}
          >
            查看报告 →
          </Button>
        </div>
      )}

      {detail.error_message && (
        <Paragraph
          style={{
            margin: 0,
            padding: '10px 14px',
            background: '#fff1f0',
            border: '1px solid #ffccc7',
            borderRadius: 8,
            fontSize: 13,
            color: '#cf1322',
          }}
        >
          <b>错误:</b> {detail.error_message}
        </Paragraph>
      )}

      {/* 流程解读:把 span 序列翻译成「这次任务做了什么」的人话 */}
      <TraceNarrative trace={detail} />

      {/* 时间线 */}
      <div>
        <Title level={5} style={{ margin: '8px 0' }}>
          ⏱ 执行时间线 · {detail.spans.length} 步
        </Title>
        <Paragraph type="secondary" style={{ fontSize: 12, margin: '0 0 12px' }}>
          按时间顺序展开,颜色区分节点类型。点任一条查看该步详情(请求内容/回复预览/工具返回)。
        </Paragraph>
        <TraceTimeline trace={detail} />
      </div>
    </Space>
  )
}

// ── 通用 KPI 小卡 ──

function SummaryStat({
  icon,
  value,
  unit,
  label,
  color,
}: {
  icon?: React.ReactNode
  value: string
  unit?: string
  label: string
  color: string
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <div style={{ fontSize: 18, fontWeight: 700, color, lineHeight: 1.1 }}>
        {value}
        {unit && <span style={{ fontSize: 12, fontWeight: 500, marginLeft: 2, color: '#98A2B3' }}>{unit}</span>}
      </div>
      <div style={{ fontSize: 11.5, color: '#98A2B3', display: 'flex', alignItems: 'center', gap: 4 }}>
        {icon}
        {label}
      </div>
    </div>
  )
}


function Kpi({
  icon,
  label,
  value,
  color = '#171719',
}: {
  icon?: React.ReactNode
  label: string
  value: string
  color?: string
}) {
  return (
    <div
      style={{
        padding: '12px 14px',
        background: '#ffffff',
        border: '1px solid #eef0f4',
        borderRadius: 12,
      }}
    >
      <div style={{ fontSize: 11.5, color: '#98A2B3', display: 'flex', alignItems: 'center', gap: 6 }}>
        {icon}
        {label}
      </div>
      <div style={{ fontSize: 20, fontWeight: 700, color, marginTop: 4, lineHeight: 1.2 }}>
        {value}
      </div>
    </div>
  )
}
