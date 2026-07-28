import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Alert,
  Button,
  Card,
  Collapse,
  Descriptions,
  Dropdown,
  Empty,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Progress,
  Segmented,
  Space,
  Spin,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  Upload,
  message,
} from 'antd'
import {
  ArrowLeftOutlined,
  ExclamationCircleFilled,
  EyeOutlined,
  InboxOutlined,
  LinkOutlined,
  LoadingOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import {
  documentApi,
  type DocumentItem,
  type DocumentPreview,
  type RetrievalValidationData,
  type SearchHit,
} from '@/api/documents'
import { imageApi, type ImageItem } from '@/api/images'
import { knowledgeBaseApi, type KnowledgeBase } from '@/api/knowledgeBases'
import { AuthenticatedImage } from '@/components/AuthenticatedImage'
import AuthenticatedFileFrame from '@/components/AuthenticatedFileFrame'
import MarkdownMessage from '@/components/MarkdownMessage'
import { FileTypeIcon, StatusTag, formatSize } from './knowledge/helpers'

const { Dragger } = Upload
const { Search } = Input

export default function KnowledgeDetailPage() {
  const { kbId = '' } = useParams()
  const navigate = useNavigate()
  const [kb, setKb] = useState<KnowledgeBase | null>(null)
  const [tab, setTab] = useState<'doc' | 'image' | 'validation'>('doc')

  useEffect(() => {
    if (!kbId) return
    knowledgeBaseApi
      .detail(kbId)
      .then(({ data }) => setKb(data))
      .catch((e) => message.error((e as Error).message))
  }, [kbId])

  return (
    <div className="fluid-page">
      <div className="kb-detail-header">
        <button
          type="button"
          className="kb-back-btn"
          onClick={() => navigate('/knowledge')}
        >
          <ArrowLeftOutlined />
          <span>返回</span>
        </button>
        <div className="kb-detail-title">
          <span className="kb-detail-icon">{kb?.icon || '📁'}</span>
          <div>
            <Typography.Title level={3} style={{ margin: 0, lineHeight: 1.2 }}>
              {kb ? kb.name : '知识库'}
            </Typography.Title>
            {kb?.description && (
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                {kb.description}
              </Typography.Text>
            )}
          </div>
        </div>
      </div>

      <Tabs
        activeKey={tab}
        onChange={(k) => setTab(k as 'doc' | 'image' | 'validation')}
        items={[
          { key: 'doc', label: '文档', children: <DocTab kbId={kbId} /> },
          { key: 'image', label: '图片', children: <ImageTab kbId={kbId} /> },
          {
            key: 'validation',
            label: '检索验证',
            children: <RetrievalValidationTab kbId={kbId} />,
          },
        ]}
      />
    </div>
  )
}

// ──────────── 文档 Tab ────────────
function DocTab({ kbId }: { kbId: string }) {
  const [list, setList] = useState<DocumentItem[]>([])
  const [loading, setLoading] = useState(false)
  const [urlModalOpen, setUrlModalOpen] = useState(false)
  const [url, setUrl] = useState('')
  const [importing, setImporting] = useState(false)
  const [searching, setSearching] = useState(false)
  const [hits, setHits] = useState<SearchHit[] | null>(null)
  const [uploading, setUploading] = useState(false)
  const pollRef = useRef<number | null>(null)
  const [preview, setPreview] = useState<DocumentPreview | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)

  const openPreview = async (d: DocumentItem) => {
    setPreviewLoading(true)
    setPreview({
      id: d.id,
      file_name: d.file_name,
      file_ext: d.file_ext,
      preview_type: d.file_ext.toLowerCase() === '.pdf' ? 'pdf' : 'text',
      preview_url: null,
      download_url: null,
      expires_in: null,
      is_markdown: false,
      source_url: d.source_url,
      content: '',
      truncated: false,
    })
    try {
      const { data } = await documentApi.preview(d.id)
      setPreview(data)
    } catch (e) {
      message.error((e as Error).message)
      setPreview(null)
    } finally {
      setPreviewLoading(false)
    }
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await documentApi.list(1, 100, undefined, kbId)
      setList(data.items)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [kbId])

  useEffect(() => {
    if (hits === null) load()
  }, [load, hits])

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
    setUploading(true)
    const hide = message.loading(`正在上传「${file.name}」，请稍候…`, 0)
    try {
      await documentApi.upload(file, kbId)
      hide()
      message.success('上传成功，正在解析')
      setHits(null)
      load()
    } catch (e) {
      hide()
      message.error((e as Error).message)
    } finally {
      setUploading(false)
    }
    return false
  }

  const onImportUrl = async () => {
    if (!url.trim()) return
    setImporting(true)
    try {
      await documentApi.importUrl(url.trim(), kbId)
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

  const onRetry = async (
    id: string,
    parser: 'auto' | 'plain' | 'pymupdf' | 'docling' = 'auto',
  ) => {
    try {
      await documentApi.retry(id, parser)
      message.success(`已使用 ${parser} 重新提交解析`)
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

  const onSearch = async (q: string) => {
    if (!q.trim()) {
      setHits(null)
      return
    }
    setSearching(true)
    try {
      const { data } = await documentApi.search(q.trim(), 8, undefined, kbId)
      setHits(data)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSearching(false)
    }
  }

  const renderRow = (d: DocumentItem) => (
    <div key={d.id} className="kb-row">
      <div className="kb-row-icon">
        <FileTypeIcon ext={d.file_ext} isUrl={d.source_type === 'url'} />
      </div>
      <div
        className="kb-row-main"
        onClick={() => openPreview(d)}
        style={{ cursor: 'pointer' }}
        title="点击查看内容"
      >
        <div className="kb-row-title-line">
          <span className="kb-row-title" title={d.file_name}>
            {d.file_name}
          </span>
          {d.tags.map((t) => (
            <Tag key={t.name} color={t.color} style={{ margin: 0, borderRadius: 5 }}>
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
        <Tooltip title="查看内容">
          <Button
            size="small"
            type="text"
            icon={<EyeOutlined />}
            onClick={() => openPreview(d)}
          />
        </Tooltip>
        {d.status !== 'parsing' && (
          <Dropdown
            trigger={['click']}
            menu={{
              items: [
                { key: 'auto', label: '自动选择解析器' },
                { key: 'plain', label: 'Plain（普通文本）' },
                { key: 'pymupdf', label: 'PyMuPDF（轻量 PDF）' },
                { key: 'docling', label: 'Docling（复杂 PDF）' },
              ],
              onClick: ({ key }) =>
                onRetry(d.id, key as 'auto' | 'plain' | 'pymupdf' | 'docling'),
            }}
          >
            <Tooltip title="选择解析器并重新解析">
              <Button size="small" type="text" icon={<ReloadOutlined />} />
            </Tooltip>
          </Dropdown>
        )}
        <Popconfirm
          title="删除文档"
          description="删除后不可恢复，确定吗？"
          icon={<ExclamationCircleFilled style={{ color: '#FF5D34' }} />}
          okText="删除"
          cancelText="取消"
          okButtonProps={{ danger: true }}
          onConfirm={() => onDelete(d.id)}
        >
          <Button size="small" type="text" danger>
            删除
          </Button>
        </Popconfirm>
      </div>
    </div>
  )

  return (
    <div>
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
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
            <Button icon={<LinkOutlined />} onClick={() => setUrlModalOpen(true)}>
              网页导入
            </Button>
          </div>
          <Dragger
            accept=".pdf,.docx,.md,.markdown,.txt,.html,.htm"
            showUploadList={false}
            beforeUpload={onUpload}
            multiple
            disabled={uploading}
            className="kb-dragger"
          >
            <p className="ant-upload-drag-icon" style={{ marginBottom: 4 }}>
              {uploading ? <LoadingOutlined /> : <InboxOutlined />}
            </p>
            <p className="ant-upload-text" style={{ fontSize: 14 }}>
              {uploading ? '正在上传，请稍候…' : '点击或拖拽文件到此上传到本知识库'}
            </p>
            <p className="ant-upload-hint" style={{ fontSize: 12 }}>
              支持 PDF / Word / Markdown / TXT / HTML
            </p>
          </Dragger>

          <Spin spinning={loading}>
            {list.length === 0 ? (
              <Empty style={{ padding: '40px 0' }} description="这个知识库还没有文档" />
            ) : (
              <div className="kb-list" style={{ marginTop: 12 }}>
                {list.map(renderRow)}
              </div>
            )}
          </Spin>
        </>
      ) : (
        <div>
          <Space style={{ marginBottom: 12 }}>
            <Button onClick={() => setHits(null)}>返回浏览</Button>
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

      <Modal
        title={
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            <EyeOutlined />
            <span
              style={{
                maxWidth: 520,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {preview?.file_name || '文档内容'}
            </span>
          </span>
        }
        open={preview !== null}
        onCancel={() => setPreview(null)}
        width={preview?.preview_type === 'pdf' ? 1080 : 860}
        className="document-preview-modal"
        footer={[
          preview?.download_url ? (
            <Button
              key="open-file"
              href={preview.download_url}
              target="_blank"
              rel="noreferrer"
              icon={<LinkOutlined />}
            >
              下载原文件
            </Button>
          ) : null,
          preview?.source_url ? (
            <Button
              key="src"
              href={preview.source_url}
              target="_blank"
              rel="noreferrer"
              icon={<LinkOutlined />}
            >
              查看原网页
            </Button>
          ) : null,
          <Button key="close" type="primary" onClick={() => setPreview(null)}>
            关闭
          </Button>,
        ]}
      >
        <Spin spinning={previewLoading}>
          <div
            className={
              preview?.preview_type === 'pdf'
                ? 'document-pdf-preview'
                : 'document-text-preview'
            }
          >
            {preview?.preview_type === 'pdf' && preview.preview_url && (
              <AuthenticatedFileFrame
                className="document-pdf-frame"
                src={preview.preview_url}
                title={preview.file_name}
              />
            )}
            {preview &&
              !previewLoading &&
              preview.preview_type !== 'pdf' &&
              !preview.content && (
              <Empty description="该文档没有可显示的文本内容" />
            )}
            {preview?.content &&
              (preview.is_markdown ? (
                <MarkdownMessage content={preview.content} />
              ) : (
                <pre
                  style={{
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    fontFamily: 'inherit',
                    fontSize: 14,
                    lineHeight: 1.8,
                    margin: 0,
                  }}
                >
                  {preview.content}
                </pre>
              ))}
            {preview?.truncated && (
              <Typography.Text
                type="secondary"
                style={{ display: 'block', marginTop: 12, fontSize: 12 }}
              >
                内容较长，仅显示前一部分。完整内容请下载原文件查看。
              </Typography.Text>
            )}
          </div>
        </Spin>
      </Modal>
    </div>
  )
}

function formatRetrievalScore(value: number | null) {
  return value === null || value === undefined ? '—' : value.toFixed(4)
}

// ──────────── 检索验证 Tab ────────────
function RetrievalValidationTab({ kbId }: { kbId: string }) {
  const [topK, setTopK] = useState(8)
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<RetrievalValidationData | null>(null)

  const runValidation = async (query: string) => {
    if (!query.trim()) {
      setData(null)
      return
    }
    setLoading(true)
    try {
      const response = await documentApi.validateRetrieval(query.trim(), kbId, topK)
      setData(response.data)
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="retrieval-validation">
      <Alert
        type="info"
        showIcon
        message="验证知识库的真实召回结果"
        description="输入问题或关键词，查看向量召回、BM25、融合、Rerank、命中子块、父块和原始 Block。结果严格限定在当前知识库。"
        style={{ marginBottom: 16 }}
      />
      <div className="retrieval-validation-toolbar">
        <Search
          placeholder="例如：文档中费用明细是多少？"
          enterButton="开始验证"
          allowClear
          loading={loading}
          onSearch={runValidation}
        />
        <Space>
          <Typography.Text type="secondary">TopK</Typography.Text>
          <InputNumber
            min={1}
            max={20}
            value={topK}
            onChange={(value) => setTopK(value || 8)}
          />
        </Space>
      </div>

      <Spin spinning={loading}>
        {!data ? (
          <Empty
            className="retrieval-validation-empty"
            description="输入问题后查看检索链路"
          />
        ) : (
          <div className="retrieval-validation-results">
            <div className="retrieval-validation-summary">
              <Space wrap>
                <Tag color="blue">召回 {data.results.length} 条</Tag>
                <Tag>向量权重 {data.vector_weight}</Tag>
                <Tag>BM25 权重 {data.bm25_weight}</Tag>
                <Tag color={data.rerank_used ? 'green' : 'default'}>
                  Rerank {data.rerank_used ? '已启用' : '未启用'}
                </Tag>
              </Space>
            </div>
            {data.rerank_error && (
              <Alert
                type="warning"
                showIcon
                message="Rerank 失败，已回退融合排序"
                description={data.rerank_error}
              />
            )}
            {data.results.length === 0 ? (
              <Empty description="当前知识库没有召回结果" />
            ) : (
              data.results.map((hit) => (
                <Card
                  key={hit.chunk_id}
                  className="retrieval-validation-card"
                  title={
                    <Space wrap>
                      <Tag color="blue">Top {hit.rank}</Tag>
                      <span>{hit.doc_name || '未知文档'}</span>
                      {hit.page_start && (
                        <Typography.Text type="secondary">
                          第 {hit.page_start}
                          {hit.page_end && hit.page_end !== hit.page_start
                            ? `–${hit.page_end}`
                            : ''}{' '}
                          页
                        </Typography.Text>
                      )}
                    </Space>
                  }
                >
                  <Descriptions
                    size="small"
                    column={{ xs: 1, sm: 2, lg: 4 }}
                    items={[
                      {
                        key: 'vector',
                        label: '向量余弦',
                        children: formatRetrievalScore(hit.scores.vector_score),
                      },
                      {
                        key: 'bm25',
                        label: 'BM25',
                        children: formatRetrievalScore(hit.scores.bm25_score),
                      },
                      {
                        key: 'fusion',
                        label: '融合分',
                        children: formatRetrievalScore(hit.scores.fusion_score),
                      },
                      {
                        key: 'rerank',
                        label: 'Rerank',
                        children: formatRetrievalScore(hit.scores.rerank_score),
                      },
                      {
                        key: 'ranks',
                        label: '阶段排名',
                        children: `向量 ${hit.stage_ranks.vector_rank ?? '—'} / BM25 ${hit.stage_ranks.bm25_rank ?? '—'} / 融合 ${hit.stage_ranks.fusion_rank ?? '—'} / 最终 ${hit.stage_ranks.final_rank}`,
                        span: 2,
                      },
                      {
                        key: 'parser',
                        label: '解析器',
                        children: `${hit.parser_name || '未知'}${hit.parser_version ? ` ${hit.parser_version}` : ''}`,
                      },
                      {
                        key: 'type',
                        label: 'Block 类型',
                        children: hit.block_types.join(', ') || '—',
                      },
                    ]}
                  />

                  {hit.heading_path.length > 0 && (
                    <div className="retrieval-heading-path">
                      标题路径：{hit.heading_path.join(' / ')}
                    </div>
                  )}
                  {hit.warnings.length > 0 && (
                    <Alert
                      type="warning"
                      showIcon
                      message={hit.warnings.join('；')}
                      style={{ marginTop: 12 }}
                    />
                  )}

                  <Collapse
                    className="retrieval-validation-collapse"
                    items={[
                      {
                        key: 'child',
                        label: `命中 Child Chunk（index ${hit.chunk_index}）`,
                        children: <div className="retrieval-content">{hit.child_content}</div>,
                      },
                      {
                        key: 'parent',
                        label: 'Parent 上下文',
                        children: <div className="retrieval-content">{hit.parent_content}</div>,
                      },
                      {
                        key: 'blocks',
                        label: `原始 Block（${hit.blocks.length}）`,
                        children:
                          hit.blocks.length > 0 ? (
                            <div className="retrieval-block-list">
                              {hit.blocks.map((block) => (
                                <div key={block.block_id} className="retrieval-block-item">
                                  <Space wrap size={4}>
                                    <Tag>{block.block_type}</Tag>
                                    <Typography.Text type="secondary">
                                      Block #{block.block_order}
                                    </Typography.Text>
                                    {block.page_start && (
                                      <Typography.Text type="secondary">
                                        第 {block.page_start} 页
                                      </Typography.Text>
                                    )}
                                  </Space>
                                  <div className="retrieval-content">{block.content}</div>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="旧数据暂无 Block" />
                          ),
                      },
                    ]}
                  />
                </Card>
              ))
            )}
          </div>
        )}
      </Spin>
    </div>
  )
}

// ──────────── 图片 Tab ────────────
function ImageTab({ kbId }: { kbId: string }) {
  const [list, setList] = useState<ImageItem[]>([])
  const [loading, setLoading] = useState(false)
  const [view, setView] = useState<'网格' | '列表'>('网格')
  const [uploading, setUploading] = useState(false)
  const pollRef = useRef<number | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await imageApi.list(1, 60, undefined, kbId)
      setList(data.items)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [kbId])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    const hasPending = list.some(
      (i) => i.status === 'pending' || i.status === 'processing',
    )
    if (hasPending && pollRef.current === null) {
      pollRef.current = window.setInterval(load, 3000)
    } else if (!hasPending && pollRef.current !== null) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
    return () => {
      if (pollRef.current !== null) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [list, load])

  const onUpload = async (file: File) => {
    setUploading(true)
    const hide = message.loading(`正在上传「${file.name}」，请稍候…`, 0)
    try {
      await imageApi.upload(file, kbId)
      hide()
      message.success('上传成功，正在识别')
      load()
    } catch (e) {
      hide()
      message.error((e as Error).message)
    } finally {
      setUploading(false)
    }
    return false
  }

  const onDelete = async (id: string) => {
    try {
      await imageApi.remove(id)
      message.success('删除成功')
      load()
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  return (
    <div>
      <Dragger
        accept="image/*"
        showUploadList={false}
        beforeUpload={onUpload}
        multiple
        disabled={uploading}
        className="kb-dragger"
      >
        <p className="ant-upload-drag-icon" style={{ marginBottom: 4 }}>
          {uploading ? <LoadingOutlined /> : <InboxOutlined />}
        </p>
        <p className="ant-upload-text" style={{ fontSize: 14 }}>
          {uploading ? '正在上传，请稍候…' : '点击或拖拽图片到此上传到本知识库'}
        </p>
        <p className="ant-upload-hint" style={{ fontSize: 12 }}>
          AI 自动生成描述、物体与场景，可被搜索
        </p>
      </Dragger>

      <div style={{ display: 'flex', justifyContent: 'flex-end', margin: '8px 0' }}>
        <Segmented
          options={['网格', '列表']}
          value={view}
          onChange={(v) => setView(v as '网格' | '列表')}
        />
      </div>

      <Spin spinning={loading}>
        {list.length === 0 ? (
          <Empty style={{ padding: '40px 0' }} description="这个知识库还没有图片" />
        ) : view === '网格' ? (
          <div className="kb-img-grid">
            {list.map((img) => (
              <div key={img.id} className="kb-img-card">
                <div className="kb-img-thumb">
                  <AuthenticatedImage
                    src={img.url}
                    alt={img.file_name}
                    style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }}
                  />
                </div>
                <div className="kb-img-foot">
                  <span className="kb-img-name" title={img.file_name}>
                    {img.file_name}
                  </span>
                  <Popconfirm
                    title="删除图片"
                    description="删除后不可恢复，确定吗？"
                    icon={<ExclamationCircleFilled style={{ color: '#FF5D34' }} />}
                    okText="删除"
                    cancelText="取消"
                    okButtonProps={{ danger: true }}
                    onConfirm={() => onDelete(img.id)}
                  >
                    <Button size="small" type="text" danger>
                      删除
                    </Button>
                  </Popconfirm>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="kb-list">
            {list.map((img) => (
              <div key={img.id} className="kb-row">
                <div className="kb-row-icon">🖼️</div>
                <div className="kb-row-main">
                  <div className="kb-row-title" title={img.file_name}>
                    {img.file_name}
                  </div>
                  <div className="kb-row-meta">
                    <span>{img.scene || '识别中'}</span>
                  </div>
                </div>
                <div className="kb-row-actions">
                  <Popconfirm
                    title="删除图片"
                    description="删除后不可恢复，确定吗？"
                    icon={<ExclamationCircleFilled style={{ color: '#FF5D34' }} />}
                    okText="删除"
                    cancelText="取消"
                    okButtonProps={{ danger: true }}
                    onConfirm={() => onDelete(img.id)}
                  >
                    <Button size="small" type="text" danger>
                      删除
                    </Button>
                  </Popconfirm>
                </div>
              </div>
            ))}
          </div>
        )}
      </Spin>
    </div>
  )
}
