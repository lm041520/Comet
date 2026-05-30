import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Button,
  Card,
  Empty,
  Input,
  Modal,
  Popconfirm,
  Progress,
  Segmented,
  Space,
  Table,
  Tag,
  Upload,
  message,
} from 'antd'
import {
  InboxOutlined,
  LinkOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import {
  documentApi,
  type DocumentItem,
  type SearchHit,
} from '@/api/documents'
import TagFilterBar from '@/components/TagFilterBar'
import { StatusTag, formatSize, groupByDate } from './knowledge/helpers'

const { Dragger } = Upload
const { Search } = Input

type ViewMode = '列表' | '时间轴'

export default function KnowledgePage() {
  const [list, setList] = useState<DocumentItem[]>([])
  const [loading, setLoading] = useState(false)
  const [view, setView] = useState<ViewMode>('列表')
  const [activeTag, setActiveTag] = useState<string>()
  const [urlModalOpen, setUrlModalOpen] = useState(false)
  const [url, setUrl] = useState('')
  const [importing, setImporting] = useState(false)
  // 检索模式
  const [searching, setSearching] = useState(false)
  const [hits, setHits] = useState<SearchHit[] | null>(null)
  const pollRef = useRef<number | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await documentApi.list(1, 100, activeTag)
      setList(data.items)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [activeTag])

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

  const tagsCell = (tags: DocumentItem['tags']) =>
    tags.length
      ? tags.map((t) => (
          <Tag key={t.name} color={t.color}>
            {t.name}
          </Tag>
        ))
      : '-'

  const columns: ColumnsType<DocumentItem> = [
    {
      title: '文件名',
      dataIndex: 'file_name',
      render: (name, r) => (
        <Space>
          {name}
          {r.source_type === 'url' && <Tag color="blue">网页</Tag>}
        </Space>
      ),
    },
    { title: '大小', dataIndex: 'file_size', width: 100, render: (s) => formatSize(s) },
    { title: '标签', dataIndex: 'tags', render: tagsCell },
    {
      title: '状态',
      dataIndex: 'status',
      width: 170,
      render: (status, r) => (
        <Space>
          <StatusTag status={status} />
          {status === 'parsing' && (
            <Progress percent={Math.round(r.progress * 100)} size="small" style={{ width: 70 }} />
          )}
          {status === 'done' && <span style={{ color: '#A8A9AA' }}>{r.chunk_num} 块</span>}
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      render: (_, r) => (
        <Space size="small">
          {r.status === 'failed' && (
            <Button size="small" icon={<ReloadOutlined />} onClick={() => onRetry(r.id)}>
              重试
            </Button>
          )}
          <Popconfirm title="确定删除该文档？" onConfirm={() => onDelete(r.id)}>
            <Button size="small" type="link" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      <Card
        title="知识库"
        extra={
          <Space>
            <Button icon={<LinkOutlined />} onClick={() => setUrlModalOpen(true)}>
              网页导入
            </Button>
          </Space>
        }
      >
        <Search
          placeholder="输入关键词语义检索（清空回到浏览）"
          allowClear
          enterButton="检索"
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
              style={{ marginBottom: 16 }}
            >
              <p className="ant-upload-drag-icon">
                <InboxOutlined />
              </p>
              <p className="ant-upload-text">点击或拖拽文件到此区域上传</p>
              <p className="ant-upload-hint">支持 PDF / Word / Markdown / TXT / HTML</p>
            </Dragger>

            <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 8 }}>
              <TagFilterBar active={activeTag} scope="document" onChange={setActiveTag} />
              <Segmented
                options={['列表', '时间轴']}
                value={view}
                onChange={(v) => setView(v as ViewMode)}
              />
            </Space>

            {view === '列表' ? (
              <Table
                rowKey="id"
                loading={loading}
                columns={columns}
                dataSource={list}
                pagination={false}
                locale={{ emptyText: <Empty description="还没有文档，上传一个试试" /> }}
              />
            ) : (
              <Timeline list={list} tagsCell={tagsCell} onDelete={onDelete} />
            )}
          </>
        ) : (
          <SearchResult hits={hits} onBack={() => setHits(null)} />
        )}
      </Card>

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
  tagsCell,
  onDelete,
}: {
  list: DocumentItem[]
  tagsCell: (tags: DocumentItem['tags']) => React.ReactNode
  onDelete: (id: string) => void
}) {
  if (!list.length) return <Empty description="暂无文档" />
  const groups = groupByDate(list)
  return (
    <div style={{ paddingLeft: 8 }}>
      {groups.map((g) => (
        <div key={g.date} style={{ position: 'relative', paddingLeft: 24, paddingBottom: 8 }}>
          <div
            style={{
              position: 'absolute',
              left: 0,
              top: 0,
              bottom: 0,
              width: 2,
              background: '#e8e8e8',
            }}
          />
          <div style={{ position: 'relative', marginBottom: 12 }}>
            <div
              style={{
                position: 'absolute',
                left: -29,
                top: 4,
                width: 10,
                height: 10,
                borderRadius: '50%',
                background: '#155EEF',
              }}
            />
            <span style={{ fontWeight: 600, color: '#171719' }}>{g.date}</span>
          </div>
          {g.items.map((d) => (
            <Card key={d.id} size="small" style={{ marginBottom: 10 }}>
              <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                <Space>
                  <span style={{ fontWeight: 500 }}>{d.file_name}</span>
                  {d.source_type === 'url' && <Tag color="blue">网页</Tag>}
                  <StatusTag status={d.status} />
                  {tagsCell(d.tags)}
                </Space>
                <Popconfirm title="确定删除？" onConfirm={() => onDelete(d.id)}>
                  <Button size="small" type="link" danger>
                    删除
                  </Button>
                </Popconfirm>
              </Space>
            </Card>
          ))}
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
          <Card key={h.chunk_id} size="small" style={{ marginBottom: 8 }}>
            <div style={{ marginBottom: 4 }}>
              <Tag color="blue">{h.doc_name}</Tag>
              <Tag>score {h.score}</Tag>
            </div>
            <div style={{ color: '#475467' }}>{h.content}</div>
          </Card>
        ))
      ) : (
        <Empty description="没有找到相关内容" />
      )}
    </div>
  )
}
