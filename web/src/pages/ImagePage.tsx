import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Button,
  Card,
  Col,
  Empty,
  Image,
  Input,
  Modal,
  Popconfirm,
  Row,
  Segmented,
  Space,
  Spin,
  Tag,
  Upload,
  message,
} from 'antd'
import { DeleteOutlined, InboxOutlined } from '@ant-design/icons'
import {
  imageApi,
  type ImageItem,
  type ImageSearchHit,
} from '@/api/images'
import TagFilterBar from '@/components/TagFilterBar'
import { groupByDate } from './knowledge/helpers'

const { Search } = Input

type ViewMode = '网格' | '时间轴'

const STATUS_TEXT: Record<string, string> = {
  pending: '待处理',
  processing: '识别中',
  done: '已完成',
  failed: '失败',
}

function ImageCard({
  img,
  onClick,
  onDelete,
}: {
  img: ImageItem
  onClick: () => void
  onDelete: (id: string) => void
}) {
  return (
    <Card
      hoverable
      size="small"
      cover={
        <div
          style={{
            height: 150,
            overflow: 'hidden',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: '#f0f2f5',
            cursor: 'pointer',
          }}
          onClick={onClick}
        >
          <img
            src={img.url}
            alt={img.file_name}
            style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }}
          />
        </div>
      }
      styles={{ body: { padding: 8 } }}
    >
      <div
        style={{
          fontSize: 12,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        {img.status === 'done' ? (
          <Space size={2} wrap>
            {img.scene && <Tag color="success">{img.scene}</Tag>}
            {img.tags.map((t) => (
              <Tag key={t.name} color={t.color}>
                {t.name}
              </Tag>
            ))}
          </Space>
        ) : (
          <Tag color={img.status === 'failed' ? 'error' : 'processing'}>
            {STATUS_TEXT[img.status]}
          </Tag>
        )}
        <Popconfirm title="删除该图片？" onConfirm={() => onDelete(img.id)}>
          <DeleteOutlined style={{ color: '#FF5D34' }} />
        </Popconfirm>
      </div>
    </Card>
  )
}

export default function ImagePage() {
  const [list, setList] = useState<ImageItem[]>([])
  const [loading, setLoading] = useState(false)
  const [view, setView] = useState<ViewMode>('网格')
  const [activeTag, setActiveTag] = useState<string>()
  const [detail, setDetail] = useState<ImageItem | null>(null)
  const [searching, setSearching] = useState(false)
  const [hits, setHits] = useState<(ImageSearchHit & { img?: ImageItem })[] | null>(null)
  const pollRef = useRef<number | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await imageApi.list(1, 60, activeTag)
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

  useEffect(() => {
    const hasPending = list.some(
      (i) => i.status === 'pending' || i.status === 'processing',
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
      await imageApi.upload(file)
      message.success('上传成功，正在识别')
      setHits(null)
      load()
    } catch (e) {
      message.error((e as Error).message)
    }
    return false
  }

  const onDelete = async (id: string) => {
    try {
      await imageApi.remove(id)
      message.success('删除成功')
      setDetail(null)
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
      const { data } = await imageApi.search(q.trim(), 12)
      // 检索命中的是 chunk，按 source_id 找回图片用于展示
      const detailed = await Promise.all(
        data.map(async (h) => {
          try {
            const d = h.source_id ? (await imageApi.detail(h.source_id)).data : undefined
            return { ...h, img: d }
          } catch {
            return { ...h }
          }
        }),
      )
      setHits(detailed)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSearching(false)
    }
  }

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      <Card title="图片库">
        <Search
          placeholder="输入关键词检索图片（按 AI 描述/OCR，清空回到浏览）"
          allowClear
          enterButton="检索"
          loading={searching}
          onSearch={onSearch}
          style={{ marginBottom: 16 }}
        />

        {hits === null ? (
          <>
            <Upload.Dragger
              accept=".jpg,.jpeg,.png,.webp,.gif,.bmp"
              showUploadList={false}
              beforeUpload={onUpload}
              multiple
              style={{ marginBottom: 16 }}
            >
              <p className="ant-upload-drag-icon">
                <InboxOutlined />
              </p>
              <p className="ant-upload-text">点击或拖拽图片上传</p>
              <p className="ant-upload-hint">AI 自动生成描述、OCR、物体与场景，可被搜索</p>
            </Upload.Dragger>

            <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 8 }}>
              <TagFilterBar active={activeTag} scope="image" onChange={setActiveTag} />
              <Segmented
                options={['网格', '时间轴']}
                value={view}
                onChange={(v) => setView(v as ViewMode)}
              />
            </Space>

            {loading && !list.length ? (
              <div style={{ textAlign: 'center', padding: 40 }}>
                <Spin />
              </div>
            ) : !list.length ? (
              <Empty description="还没有图片，上传一张试试" />
            ) : view === '网格' ? (
              <Row gutter={[16, 16]}>
                {list.map((img) => (
                  <Col xs={12} sm={8} md={6} lg={4} key={img.id}>
                    <ImageCard img={img} onClick={() => setDetail(img)} onDelete={onDelete} />
                  </Col>
                ))}
              </Row>
            ) : (
              <ImageTimeline list={list} onClick={setDetail} onDelete={onDelete} />
            )}
          </>
        ) : (
          <ImageSearchResult
            hits={hits}
            onBack={() => setHits(null)}
            onClick={setDetail}
          />
        )}
      </Card>

      <Modal
        title={detail?.file_name}
        open={!!detail}
        onCancel={() => setDetail(null)}
        footer={null}
        width={720}
      >
        {detail && (
          <Row gutter={16}>
            <Col span={12}>
              <Image src={detail.url} alt={detail.file_name} />
            </Col>
            <Col span={12}>
              <p style={{ fontWeight: 600 }}>AI 描述</p>
              <p style={{ color: '#475467' }}>{detail.description || '—'}</p>
              {detail.scene && (
                <p>
                  <Tag color="blue">场景：{detail.scene}</Tag>
                </p>
              )}
              {detail.tags?.length ? (
                <p>{detail.tags.map((t) => <Tag key={t.name} color={t.color}>{t.name}</Tag>)}</p>
              ) : null}
              {detail.objects?.length ? (
                <p>物体：{detail.objects.map((o) => <Tag key={o}>{o}</Tag>)}</p>
              ) : null}
              {detail.ocr_text ? (
                <>
                  <p style={{ fontWeight: 600, marginTop: 12 }}>OCR 文字</p>
                  <p style={{ color: '#475467', whiteSpace: 'pre-wrap' }}>{detail.ocr_text}</p>
                </>
              ) : null}
            </Col>
          </Row>
        )}
      </Modal>
    </div>
  )
}

function ImageTimeline({
  list,
  onClick,
  onDelete,
}: {
  list: ImageItem[]
  onClick: (img: ImageItem) => void
  onDelete: (id: string) => void
}) {
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
            <span style={{ fontWeight: 600 }}>{g.date}</span>
          </div>
          <Row gutter={[16, 16]} style={{ marginBottom: 8 }}>
            {g.items.map((img) => (
              <Col xs={12} sm={8} md={6} lg={4} key={img.id}>
                <ImageCard img={img} onClick={() => onClick(img)} onDelete={onDelete} />
              </Col>
            ))}
          </Row>
        </div>
      ))}
    </div>
  )
}

function ImageSearchResult({
  hits,
  onBack,
  onClick,
}: {
  hits: (ImageSearchHit & { img?: ImageItem })[]
  onBack: () => void
  onClick: (img: ImageItem) => void
}) {
  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Button onClick={onBack}>返回浏览</Button>
        <span style={{ color: '#667085' }}>命中 {hits.length} 张相关图片</span>
      </Space>
      {hits.length ? (
        <Row gutter={[16, 16]}>
          {hits.map((h) =>
            h.img ? (
              <Col xs={12} sm={8} md={6} lg={4} key={h.chunk_id}>
                <ImageCard
                  img={h.img}
                  onClick={() => onClick(h.img!)}
                  onDelete={() => {}}
                />
              </Col>
            ) : null,
          )}
        </Row>
      ) : (
        <Empty description="没有找到相关图片" />
      )}
    </div>
  )
}
