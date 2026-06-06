import { Tag } from 'antd'
import {
  FileMarkdownOutlined,
  FilePdfOutlined,
  FileTextOutlined,
  FileWordOutlined,
  GlobalOutlined,
  Html5Outlined,
} from '@ant-design/icons'
import type { DocStatus } from '@/api/documents'

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

// 按扩展名 / 来源给出文件类型图标 + 配色
const ICON_META: Record<string, { color: string; bg: string; el: React.ReactNode }> = {
  pdf: { color: '#E5484D', bg: '#FDECEC', el: <FilePdfOutlined /> },
  doc: { color: '#155EEF', bg: '#EAF0FE', el: <FileWordOutlined /> },
  docx: { color: '#155EEF', bg: '#EAF0FE', el: <FileWordOutlined /> },
  md: { color: '#0E9384', bg: '#E6F6F4', el: <FileMarkdownOutlined /> },
  markdown: { color: '#0E9384', bg: '#E6F6F4', el: <FileMarkdownOutlined /> },
  html: { color: '#DD6B20', bg: '#FEF3E8', el: <Html5Outlined /> },
  htm: { color: '#DD6B20', bg: '#FEF3E8', el: <Html5Outlined /> },
  txt: { color: '#667085', bg: '#F2F4F7', el: <FileTextOutlined /> },
}

export function FileTypeIcon({ ext, isUrl }: { ext: string; isUrl: boolean }) {
  const meta = isUrl
    ? { color: '#0BA5EC', bg: '#E7F6FE', el: <GlobalOutlined /> }
    : ICON_META[(ext || '').toLowerCase().replace('.', '')] ?? {
        color: '#667085',
        bg: '#F2F4F7',
        el: <FileTextOutlined />,
      }
  return (
    <span
      style={{
        width: 38,
        height: 38,
        borderRadius: 10,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: meta.bg,
        color: meta.color,
        fontSize: 19,
      }}
    >
      {meta.el}
    </span>
  )
}

/** 把带 created_at 的列表按 年-月-日 分组，返回 [{date, items}]，按日期倒序 */
export function groupByDate<T extends { created_at: string }>(
  items: T[],
): { date: string; items: T[] }[] {
  const map = new Map<string, T[]>()
  for (const it of items) {
    const d = it.created_at.slice(0, 10) // YYYY-MM-DD
    if (!map.has(d)) map.set(d, [])
    map.get(d)!.push(it)
  }
  return Array.from(map.entries())
    .sort((a, b) => (a[0] < b[0] ? 1 : -1))
    .map(([date, list]) => ({ date, items: list }))
}

const STATUS_META: Record<DocStatus, { color: string; text: string }> = {
  pending: { color: 'default', text: '待处理' },
  parsing: { color: 'processing', text: '解析中' },
  done: { color: 'success', text: '已完成' },
  failed: { color: 'error', text: '失败' },
}

export function StatusTag({ status }: { status: DocStatus }) {
  const meta = STATUS_META[status]
  return <Tag color={meta.color}>{meta.text}</Tag>
}
