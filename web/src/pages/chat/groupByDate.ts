import type { Conversation } from '@/api/chat'

export interface ConvGroup {
  key: string // 分组标识（用于折叠状态）
  label: string // 显示标题
  items: Conversation[]
}

function dayStart(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

// 按 updated_at 把会话分组：今天 / 昨天 / 近 7 天 / 更早按「YYYY年M月」
export function groupConversationsByDate(convs: Conversation[]): ConvGroup[] {
  const now = new Date()
  const today = dayStart(now)
  const oneDay = 86400000
  const yesterday = today - oneDay
  const weekAgo = today - 6 * oneDay // 含今天往前 7 天

  const buckets: { key: string; label: string; items: Conversation[] }[] = []
  const getBucket = (key: string, label: string) => {
    let b = buckets.find((x) => x.key === key)
    if (!b) {
      b = { key, label, items: [] }
      buckets.push(b)
    }
    return b
  }

  for (const c of convs) {
    const t = c.updated_at ? new Date(c.updated_at) : null
    if (!t || Number.isNaN(t.getTime())) {
      getBucket('unknown', '更早').items.push(c)
      continue
    }
    const ds = dayStart(t)
    if (ds === today) {
      getBucket('today', '今天').items.push(c)
    } else if (ds === yesterday) {
      getBucket('yesterday', '昨天').items.push(c)
    } else if (ds >= weekAgo) {
      getBucket('week', '近 7 天').items.push(c)
    } else {
      const key = `${t.getFullYear()}-${t.getMonth() + 1}`
      getBucket(key, `${t.getFullYear()}年${t.getMonth() + 1}月`).items.push(c)
    }
  }

  // 固定顺序：今天 > 昨天 > 近7天 > 各月份（新→旧）> 未知
  const order = ['today', 'yesterday', 'week']
  return buckets.sort((a, b) => {
    const ia = order.indexOf(a.key)
    const ib = order.indexOf(b.key)
    if (ia !== -1 || ib !== -1) {
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
    }
    if (a.key === 'unknown') return 1
    if (b.key === 'unknown') return -1
    // 月份倒序
    return a.key < b.key ? 1 : -1
  })
}
