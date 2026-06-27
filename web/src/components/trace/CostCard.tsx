/**
 * 仪表盘成本与执行卡 —— V0.0.5 ③ M8
 *
 * 数据源:GET /api/traces/cost-summary?days=30
 * 展示:
 * - 4 宫 KPI:总任务数 / 总成本 / 总 tokens / 缓存命中率
 * - 按 model 成本饼图(谁最贵)
 * - 按 task_type 调用次数 + 平均耗时(谁最频繁/谁最慢)
 * 没数据时整卡不显示,避免新用户看到空卡。
 */
import { useEffect, useMemo, useState } from 'react'
import { Card, Segmented, Space, Spin, Typography } from 'antd'
import { Link } from 'react-router-dom'

import { traceApi, type CostSummary } from '@/api/traces'

const { Text } = Typography


function fmtCost(cny: number): string {
  if (cny === 0) return '¥0'
  if (cny < 0.01) return `¥${cny.toFixed(5)}`
  if (cny < 1) return `¥${cny.toFixed(4)}`
  return `¥${cny.toFixed(2)}`
}

function fmtNum(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

export default function CostCard() {
  const [days, setDays] = useState<number>(30)
  const [data, setData] = useState<CostSummary | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    traceApi
      .costSummary(days)
      .then((res) => {
        if (!cancelled) setData(res.data)
      })
      .catch(() => {
        if (!cancelled) setData(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [days])

  // ── 衍生值 ──
  // 注意:所有 hook 必须在任何 early return 之前调用(React Hooks 规则)。
  const cacheRate = useMemo(() => {
    if (!data || data.total_input_tokens === 0) return 0
    return (data.total_cached_tokens / data.total_input_tokens) * 100
  }, [data])

  const avgCostPerTask = useMemo(() => {
    if (!data || data.total_traces === 0) return 0
    return data.total_cost_cny / data.total_traces
  }, [data])

  // 没数据 → 整卡不渲染(对新用户友好)。
  // 必须放在所有 hook 调用之后,否则前后两次渲染 hook 数量不一致会触发
  // 「Rendered more hooks than during the previous render」。
  if (!loading && (!data || data.total_traces === 0)) {
    return null
  }

  return (
    <Card
      title={
        <Space>
          <span>💰 成本与执行</span>
          <Text type="secondary" style={{ fontSize: 12 }}>
            Agent 任务的真实 token 与成本透视
          </Text>
        </Space>
      }
      style={{ marginBottom: 22, borderRadius: 16 }}
      extra={
        <Space>
          <Segmented
            size="small"
            value={days}
            onChange={(v) => setDays(v as number)}
            options={[
              { label: '近 7 天', value: 7 },
              { label: '近 30 天', value: 30 },
              { label: '近 90 天', value: 90 },
            ]}
          />
          <Link to="/traces" style={{ fontSize: 12 }}>
            查看全部轨迹 →
          </Link>
        </Space>
      }
    >
      {loading || !data ? (
        <div style={{ textAlign: 'center', padding: 32 }}>
          <Spin />
        </div>
      ) : (
        <div>
          {/* 4 宫 KPI */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
              gap: 10,
              marginBottom: 16,
            }}
          >
            <Kpi label="任务总数" value={String(data.total_traces)} unit="次" color="#155EEF" />
            <Kpi
              label="总成本"
              value={fmtCost(data.total_cost_cny)}
              sub={`平均 ${fmtCost(avgCostPerTask)} / 次`}
              color="#FAAD14"
            />
            <Kpi
              label="总 tokens"
              value={fmtNum(data.total_input_tokens + data.total_output_tokens)}
              sub={`输入 ${fmtNum(data.total_input_tokens)} / 输出 ${fmtNum(data.total_output_tokens)}`}
              color="#7C4DFF"
            />
            <Kpi
              label="缓存命中率"
              value={`${cacheRate.toFixed(1)}%`}
              sub={`节省 ${fmtNum(data.total_cached_tokens)} tokens`}
              color={cacheRate >= 10 ? '#369F21' : '#98A2B3'}
            />
          </div>
        </div>
      )}
    </Card>
  )
}


function Kpi({
  label,
  value,
  unit,
  sub,
  color,
}: {
  label: string
  value: string
  unit?: string
  sub?: string
  color: string
}) {
  return (
    <div
      style={{
        padding: '12px 14px',
        background: '#ffffff',
        border: '1px solid #eef0f4',
        borderRadius: 10,
      }}
    >
      <div style={{ fontSize: 11.5, color: '#98A2B3' }}>{label}</div>
      <div
        style={{
          fontSize: 20,
          fontWeight: 700,
          color,
          lineHeight: 1.15,
          marginTop: 4,
        }}
      >
        {value}
        {unit && <span style={{ fontSize: 12, color: '#98A2B3', marginLeft: 2, fontWeight: 500 }}>{unit}</span>}
      </div>
      {sub && <div style={{ fontSize: 10.5, color: '#98A2B3', marginTop: 4 }}>{sub}</div>}
    </div>
  )
}
