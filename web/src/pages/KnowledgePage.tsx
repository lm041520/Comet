import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Button,
  Empty,
  Input,
  Modal,
  Popconfirm,
  Progress,
  Segmented,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
  Upload,
  message,
} from 'antd'
import {
  InboxOutlined,
  LinkOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import {
  documentApi,
  type DocumentItem,
  type SearchHit,
} from '@/api/documents'
import { favoriteApi } from '@/api/favorites'
import FavoriteButton from '@/components/FavoriteButton'
import TagFilterBar from '@/components/TagFilterBar'
import {
  FileTypeIcon,
  StatusTag,
  formatSize,
  groupByDate,
} from './knowledge/helpers'

const { Dragger } = Upload
const { Search } = Input

type ViewMode = '列表' | '时间轴'

export default function KnowledgePage() {
  const [list, setList] = useState<DocumentItem[]>([])
  const [loading, setLoading] = useState(false)
  const [view, setView] = useState<ViewMode>('时间轴')
  const [activeTag, setActiveTag] = useState<string>()
  const [favMap, setFavMap] = useState<Record<string, string>>({})
  const [urlModalOpen, setUrlModalOpen] = useState(false)
  const [url, setUrl] = useState('')
  const [importing, setImporting] = useState(false)
  // 检索模式
  const [searching, setSearching] = useState(false)
  const [hits, setHits] = useState<SearchHit[] | null>(null)
  const pollRef = useRef<number | null>(null)

  const loadFavorites = async () => {
    try {
      const { data } = await favoriteApi.list('document')
      const map: Record<string, string> = {}
      data.forEach((f) => {
        map[f.target_id] = f.id
      })
      setFavMap(map)
    } catch {
      // 收藏态加载失败不影响主流程
    }
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await documentApi.list(1, 100, activeTag)
      setList(data.items)
      loadFavorites()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [activeTag])

  const onFavChange = (id: string, favId: string | null) => {
    setFavMap((prev) => {
      const next = { ...prev }
      if (favId) next[id] = favId
      else delete next[id]
      return next
    })
  }

  const favSnapshot = (d: DocumentItem) => ({
    title: d.file_name,
    summary: `${d.chunk_num} 块 · ${d.source_type === 'url' ? '网页' : '文件'}`,
  })

  useEffect(() => {
    if (hits === null) load()
  }, [load, hits])

  // 解析中轮询
  useEffect(() => {
    const hasPending = list.some(
      (d) => d.status === 'pending' || d.status === 'parsing',
    )
    if (hits === null && hasPending && pollRef.current === null) {
      pollRef.current = window.setInterval(load, 3000)
    } else if ((hits !== null || !hasPending) && pollRef.current !== null) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
    return () => {
      if (pollRef.current !== null) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [list, load, hits])

  const onUpload = async (file: File) => {
    try {
      await documentApi.upload(file)
      message.success('上传成功，正在解析')
      setHits(null)
      load()
    } catch (e) {
      message.error((e as Error).message)
    }
    return false
  }

  const onImportUrl = async () => {
    if (!url.trim()) return
    setImporting(true)
    try {
      await documentApi.importUrl(url.trim())
      message.success('导入成功，正在解析')
      setUrlModalOpen(false)
      setUrl('')
      setHits(null)
      load()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setImporting(false)
    }
  }

  const onRetry = async (id: string) => {
    try {
      await documentApi.retry(id)
      message.success('已重新提交解析')
      load()
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const onDelete = async (id: string) => {
    try {
      await documentApi.remove(id)
      message.success('删除成功')
      load()
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  // 检索模式：输入关键词进入；清空回到浏览
  const onSearch = async (q: string) => {
    if (!q.trim()) {
      setHits(null)
      return
    }
    setSearching(true)
    try {
      const { data } = await documentApi.search(q.trim(), 8)
      setHits(data)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSearching(false)
    }
  }

  // 单条文档行（列表 / 时间轴共用）
  const renderRow = (d: DocumentItem) => (
    <div key={d.id} className="kb-row">
      <div className="kb-row-icon">
        <FileTypeIcon ext={d.file_ext} isUrl={d.source_type === 'url'} />
      </div>
      <div className="kb-row-main">
        <div className="kb-row-title-line">
          <span className="kb-row-title" title={d.file_name}>
            {d.file_name}
          </span>
          {d.tags.map((t) => (
            <Tag
              key={t.name}
              color={t.color}
              style={{ margin: 0, borderRadius: 5 }}
            >
              {t.name}
            </Tag>
          ))}
        </div>
        <div className="kb-row-meta">
          <StatusTag status={d.status} />
          {d.status === 'parsing' && (
            <Progress
              percent={Math.round(d.progress * 100)}
              size="small"
              style={{ width: 90 }}
            />
          )}
          {d.status === 'done' && <span>{d.chunk_num} 块</span>}
          <span className="kb-dot">·</span>
          <span>{d.source_type === 'url' ? '网页' : formatSize(d.file_size)}</span>
        </div>
      </div>
      <div className="kb-row-actions">
        <FavoriteButton
          targetType="document"
          targetId={d.id}
          initialFavId={favMap[d.id] ?? null}
          snapshot={favSnapshot(d)}
          onChange={onFavChange}
        />
        {d.status === 'failed' && (
          <Tooltip title="重新解析">
            <Button
              size="small"
              type="text"
              icon={<ReloadOutlined />}
              onClick={() => onRetry(d.id)}
            />
          </Tooltip>
        )}
        <Popconfirm title="确定删除该文档？" onConfirm={() => onDelete(d.id)}>
          <Button size="small" type="text" danger>
            删除
          </Button>
        </Popconfirm>
      </div>
    </div>
  )

  return (
    <div className="fluid-page">
      <div className="kb-header">
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>
            知识库
          </Typography.Title>
          <Typography.Text type="secondary">
            上传文档或导入网页，自动解析、分块、打标签，支持语义检索
          </Typography.Text>
        </div>
        <Button icon={<LinkOutlined />} onClick={() => setUrlModalOpen(true)}>
          网页导入
        </Button>
      </div>

      <Search
        placeholder="输入关键词语义检索（清空回到浏览）"
        allowClear
        enterButton="检索"
        size="large"
        loading={searching}
        onSearch={onSearch}
        style={{ marginBottom: 16 }}
      />

      {hits === null ? (
        <>
          <Dragger
            accept=".pdf,.docx,.md,.markdown,.txt,.html,.htm"
            showUploadList={false}
            beforeUpload={onUpload}
            multiple
            className="kb-dragger"
          >
            <p className="ant-upload-drag-icon" style={{ marginBottom: 4 }}>
              <InboxOutlined />
            </p>
            <p className="ant-upload-text" style={{ fontSize: 14 }}>
              点击或拖拽文件到此上传
            </p>
            <p className="ant-upload-hint" style={{ fontSize: 12 }}>
              支持 PDF / Word / Markdown / TXT / HTML
            </p>
          </Dragger>

          <div className="kb-toolbar">
            <TagFilterBar active={activeTag} scope="document" onChange={setActiveTag} />
            <Segmented
              options={['时间轴', '列表']}
              value={view}
              onChange={(v) => setView(v as ViewMode)}
            />
          </div>

          <Spin spinning={loading}>
            {list.length === 0 ? (
              <Empty
                style={{ padding: '48px 0' }}
                description="还没有文档，上传一个试试"
              />
            ) : view === '列表' ? (
              <div className="kb-list">{list.map(renderRow)}</div>
            ) : (
              <Timeline list={list} renderRow={renderRow} />
            )}
          </Spin>
        </>
      ) : (
        <SearchResult hits={hits} onBack={() => setHits(null)} />
      )}

      <Modal
        title="从网页导入"
        open={urlModalOpen}
        onCancel={() => setUrlModalOpen(false)}
        onOk={onImportUrl}
        confirmLoading={importing}
      >
        <Input
          placeholder="https://..."
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onPressEnter={onImportUrl}
        />
      </Modal>
    </div>
  )
}

// 时间轴视图：按日期分组，竖线展示
function Timeline({
  list,
  renderRow,
}: {
  list: DocumentItem[]
  renderRow: (d: DocumentItem) => React.ReactNode
}) {
  if (!list.length) return <Empty description="暂无文档" />
  const groups = groupByDate(list)
  return (
    <div className="kb-timeline">
      {groups.map((g) => (
        <div key={g.date} className="kb-tl-group">
          <div className="kb-tl-date">
            <span className="kb-tl-dot" />
            {g.date}
          </div>
          <div className="kb-list">{g.items.map(renderRow)}</div>
        </div>
      ))}
    </div>
  )
}

// 检索结果
function SearchResult({ hits, onBack }: { hits: SearchHit[]; onBack: () => void }) {
  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Button onClick={onBack}>返回浏览</Button>
        <span style={{ color: '#667085' }}>命中 {hits.length} 条相关片段</span>
      </Space>
      {hits.length ? (
        hits.map((h) => (
          <div key={h.chunk_id} className="kb-hit">
            <div className="kb-hit-head">
              <Tag color="blue" style={{ margin: 0 }}>
                {h.doc_name}
              </Tag>
              <span className="kb-hit-score">相关度 {h.score}</span>
            </div>
            <div className="kb-hit-content">{h.content}</div>
          </div>
        ))
      ) : (
        <Empty description="没有找到相关内容" />
      )}
    </div>
  )
}
