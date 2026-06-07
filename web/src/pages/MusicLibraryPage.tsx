import { useCallback, useEffect, useRef, useState } from 'react'
import {
  App,
  Button,
  ConfigProvider,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Space,
  Spin,
  theme as antdTheme,
  Tooltip,
  Typography,
  Upload,
} from 'antd'
import type { UploadFile } from 'antd'
import {
  CaretRightOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  TagsOutlined,
  ThunderboltOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import { musicApi, type MiguSearchHit, type Song } from '@/api/music'
import { useMusicStore } from '@/stores/musicStore'

const { Text } = Typography

// 情绪坐标 → 中文描述
function moodLabel(valence: number, arousal: number): string {
  const v = valence >= 0.15 ? '积极' : valence <= -0.15 ? '消极' : '中性'
  const a = arousal >= 0.6 ? '激昂' : arousal <= 0.3 ? '舒缓' : '适中'
  return `${v}·${a}`
}

// 情绪坐标 → 光晕色（valence 决定色相暖冷，arousal 决定鲜艳度）
function moodGlow(valence: number, arousal: number): string {
  // valence -1~1 → 色相：消极偏蓝紫(250)、中性青(190)、积极暖(40)
  const hue = valence >= 0 ? 40 + (1 - valence) * 150 : 250 + valence * 60
  const sat = 60 + arousal * 30
  const light = 55 + arousal * 8
  return `hsla(${Math.round(hue)}, ${Math.round(sat)}%, ${Math.round(light)}%, 0.6)`
}

const tagStatusMap: Record<string, { color: string; text: string }> = {
  pending: { color: 'default', text: '处理中' },
  done: { color: 'green', text: '已就绪' },
  failed: { color: 'orange', text: '处理失败' },
}

const statusBg: Record<string, string> = {
  pending: 'rgba(99,102,241,0.85)',
  done: 'rgba(54,159,33,0.85)',
  failed: 'rgba(255,150,40,0.85)',
}

// 弹窗深色主题（与音乐厅风格统一）
// 注意：全局 theme 把 colorTextBase 设成了近黑，会被继承盖过暗色算法，
// 这里显式覆盖文字/背景/边框为浅色系，保证暗底上文字可见。
const darkModalTheme = {
  algorithm: antdTheme.darkAlgorithm,
  token: {
    colorPrimary: '#6366f1',
    borderRadius: 10,
    colorTextBase: '#e8eaf2',
    colorText: 'rgba(255,255,255,0.92)',
    colorTextSecondary: 'rgba(255,255,255,0.65)',
    colorTextTertiary: 'rgba(255,255,255,0.45)',
    colorTextPlaceholder: 'rgba(255,255,255,0.35)',
    colorBgElevated: '#1c1e33',
    colorBgContainer: 'rgba(255,255,255,0.06)',
    colorBorder: 'rgba(255,255,255,0.16)',
  },
}

export default function MusicLibraryPage() {
  const { message, modal } = App.useApp()
  const [songs, setSongs] = useState<Song[]>([])
  const [loading, setLoading] = useState(false)
  const [retagging, setRetagging] = useState(false)
  const playList = useMusicStore((s) => s.playList)
  const recommend = useMusicStore((s) => s.recommend)

  const [addOpen, setAddOpen] = useState(false)
  const [editing, setEditing] = useState<Song | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await musicApi.listSongs()
      setSongs(data.items)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // 有歌曲在后台处理（pending）时，每 3s 轮询刷新，直到全部完成
  useEffect(() => {
    if (!songs.some((s) => s.tag_status === 'pending')) return
    const timer = setInterval(load, 3000)
    return () => clearInterval(timer)
  }, [songs, load])

  const onDelete = (song: Song) => {
    modal.confirm({
      title: `删除《${song.title}》？`,
      content: '将从曲库移除（含已上传的音频文件）',
      okButtonProps: { danger: true },
      onOk: async () => {
        await musicApi.removeSong(song.id)
        message.success('已删除')
        load()
      },
    })
  }

  const onRetagAll = async () => {
    setRetagging(true)
    try {
      const { data } = await musicApi.retagAll()
      message.success(`已重新处理 ${data.dispatched} 首，正在后台运行`)
      load()
    } finally {
      setRetagging(false)
    }
  }

  const onRetagOne = async (song: Song) => {
    await musicApi.retagSong(song.id)
    message.success('已重新处理，正在后台运行')
    load()
  }

  return (
    <div className="fluid-page">
      <div className="music-hall">
        <div
          style={{
            position: 'relative',
            zIndex: 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: 22,
            flexWrap: 'wrap',
            gap: 12,
          }}
        >
          <div>
            <div style={{ color: '#fff', fontSize: 24, fontWeight: 700, letterSpacing: 1 }}>
              我的音乐厅
            </div>
            <div style={{ color: 'rgba(255,255,255,0.55)', fontSize: 13, marginTop: 4 }}>
              共 {songs.length} 首 · 情绪标签由 AI 自动标注
            </div>
          </div>
          <Space className="music-actions" wrap>
            <Button
              ghost
              icon={<TagsOutlined />}
              loading={retagging}
              onClick={onRetagAll}
            >
              一键重新处理
            </Button>
            <Button ghost icon={<ThunderboltOutlined />} onClick={() => recommend()}>
              为我推荐
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setAddOpen(true)}
            >
              添加歌曲
            </Button>
          </Space>
        </div>

        {songs.length === 0 && !loading ? (
          <Empty
            description={
              <span style={{ color: 'rgba(255,255,255,0.6)' }}>
                音乐厅还空着，添加几首吧
              </span>
            }
            style={{ padding: '40px 0' }}
          />
        ) : (
          <Spin spinning={loading}>
            <div
              style={{
                position: 'relative',
                zIndex: 1,
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
                gap: 26,
              }}
            >
              {songs.map((song, idx) => (
                <SongCard
                  key={song.id}
                  song={song}
                  onPlay={() => playList(songs, idx)}
                  onEdit={() => setEditing(song)}
                  onRetag={() => onRetagOne(song)}
                  onDelete={() => onDelete(song)}
                />
              ))}
            </div>
          </Spin>
        )}
      </div>

      <AddSongModal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onDone={() => {
          setAddOpen(false)
          load()
        }}
      />
      <EditSongModal
        song={editing}
        onClose={() => setEditing(null)}
        onDone={() => {
          setEditing(null)
          load()
        }}
      />
    </div>
  )
}

// ── 炫酷专辑卡片：玻璃拟态 + 情绪光晕 + hover 放大/霓虹描边 + 脉冲播放键 ──
function SongCard({
  song,
  onPlay,
  onEdit,
  onRetag,
  onDelete,
}: {
  song: Song
  onPlay: () => void
  onEdit: () => void
  onRetag: () => void
  onDelete: () => void
}) {
  const glow = moodGlow(song.valence, song.arousal)
  const processing = song.tag_status === 'pending'
  const canPlay = song.playable && !processing
  return (
    <div
      className="album-card"
      style={{ ['--mood-glow' as string]: glow }}
    >
      <div className="album-cover">
        <div className="album-mood-glow" />
        {song.cover_url ? (
          <img className="album-cover-img" src={song.cover_url} alt={song.title} />
        ) : (
          <div
            className="album-cover-img"
            style={{
              background: `linear-gradient(135deg, ${glow}, #16182e)`,
            }}
          />
        )}

        {/* 状态角标 */}
        <span
          className="album-status"
          style={{ background: statusBg[song.tag_status] ?? statusBg.pending }}
        >
          {tagStatusMap[song.tag_status]?.text ?? song.tag_status}
        </span>

        {/* 右上操作 */}
        <div className="album-actions">
          <Tooltip title="重新处理（情绪/音源/封面）">
            <span className="album-icon-btn" onClick={onRetag}>
              <TagsOutlined />
            </span>
          </Tooltip>
          <Tooltip title="编辑">
            <span className="album-icon-btn" onClick={onEdit}>
              <EditOutlined />
            </span>
          </Tooltip>
          <Tooltip title="删除">
            <span className="album-icon-btn danger" onClick={onDelete}>
              <DeleteOutlined />
            </span>
          </Tooltip>
        </div>

        {/* 中央脉冲播放键 */}
        <div className="album-play-btn">
          <Tooltip title={processing ? '处理中…' : canPlay ? '播放' : '暂无音源'}>
            <div
              className={`album-play-disc ${canPlay ? '' : 'disabled'}`}
              onClick={() => canPlay && onPlay()}
            >
              <CaretRightOutlined />
            </div>
          </Tooltip>
        </div>

        {/* 底部信息（叠在封面上） */}
        <div className="album-info">
          <div className="album-title" title={song.title}>
            {song.title}
          </div>
          <div className="album-artist">
            {song.artist || '未知歌手'}
            {song.album ? ` · ${song.album}` : ''}
          </div>
          <div style={{ marginTop: 8, display: 'flex', gap: 5, flexWrap: 'wrap' }}>
            <span
              className="album-chip"
              style={{ background: glow, borderColor: 'transparent' }}
            >
              {moodLabel(song.valence, song.arousal)}
            </span>
            {(song.mood_tags ?? []).slice(0, 2).map((t) => (
              <span key={t} className="album-chip">
                {t}
              </span>
            ))}
            {!processing && !song.playable && (
              <span className="album-chip">无音源</span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── 添加歌曲：上传音频（可选）+ 填歌名歌手 + 咪咕搜索带出封面 ──
function AddSongModal({
  open,
  onClose,
  onDone,
}: {
  open: boolean
  onClose: () => void
  onDone: () => void
}) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [fileKey, setFileKey] = useState<string | null>(null)
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [coverUrl, setCoverUrl] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [searching, setSearching] = useState(false)
  const [hits, setHits] = useState<MiguSearchHit[]>([])
  // 监听歌名/歌手，输入即自动搜索（防抖）
  const watchTitle = Form.useWatch('title', form)
  const watchArtist = Form.useWatch('artist', form)
  // applyHit 回填表单会触发 watch，用此标记跳过紧随的自动搜索
  const skipAutoRef = useRef(false)

  const reset = () => {
    form.resetFields()
    setFileKey(null)
    setFileList([])
    setCoverUrl(null)
    setHits([])
  }

  const doSearch = useCallback(
    async (kw: string) => {
      const q = kw.trim()
      if (!q) return
      setSearching(true)
      try {
        const { data } = await musicApi.searchMigu(q)
        setHits(data)
      } catch {
        // 自动搜索失败静默，不打扰输入
      } finally {
        setSearching(false)
      }
    },
    [],
  )

  // 输入防抖自动搜索：歌名/歌手变化 600ms 后触发
  useEffect(() => {
    if (!open) return
    if (skipAutoRef.current) {
      skipAutoRef.current = false
      return
    }
    const kw = `${watchTitle || ''} ${watchArtist || ''}`.trim()
    if (kw.length < 2) {
      setHits([])
      return
    }
    const timer = setTimeout(() => void doSearch(kw), 600)
    return () => clearTimeout(timer)
  }, [watchTitle, watchArtist, open, doSearch])

  const onSearch = async () => {
    const kw = `${form.getFieldValue('title') || ''} ${form.getFieldValue('artist') || ''}`
    if (!kw.trim()) {
      message.warning('先填歌名或歌手')
      return
    }
    setSearching(true)
    try {
      const { data } = await musicApi.searchMigu(kw.trim())
      setHits(data)
      if (data.length === 0) message.info('没搜到，可手动填写')
    } finally {
      setSearching(false)
    }
  }

  const applyHit = (h: MiguSearchHit) => {
    skipAutoRef.current = true
    form.setFieldsValue({ title: h.title, artist: h.artist, album: h.album })
    setCoverUrl(h.cover_url)
    setHits([])
  }

  const onSubmit = async () => {
    const values = await form.validateFields()
    setSubmitting(true)
    try {
      await musicApi.createSong({
        title: values.title,
        artist: values.artist,
        album: values.album,
        file_key: fileKey,
        cover_url: coverUrl,
        auto_tag: true,
      })
      message.success('已加入曲库，正在后台处理（封面/歌词/情绪/音源）')
      reset()
      onDone()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <ConfigProvider theme={darkModalTheme}>
      <Modal
        title="添加歌曲"
        open={open}
      onCancel={() => {
        reset()
        onClose()
      }}
      onOk={onSubmit}
      confirmLoading={submitting}
      okText="加入曲库"
      destroyOnClose
    >
      <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
        <Form.Item
          name="title"
          label="歌名"
          rules={[{ required: true, message: '请填歌名' }]}
        >
          <Input placeholder="如：晴天" />
        </Form.Item>
        <Form.Item name="artist" label="歌手">
          <Input placeholder="如：周杰伦" />
        </Form.Item>
        <Form.Item name="album" label="专辑（可选）">
          <Input />
        </Form.Item>

        <Space style={{ marginBottom: 12 }} align="center">
          <Button loading={searching} onClick={onSearch}>
            搜索带出封面/信息
          </Button>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {searching ? '搜索中…' : '输入歌名/歌手会自动搜索'}
          </Text>
          {coverUrl && (
            <img
              src={coverUrl}
              alt=""
              style={{ width: 40, height: 40, borderRadius: 6, objectFit: 'cover' }}
            />
          )}
        </Space>

        {hits.length > 0 && (
          <List
            size="small"
            bordered
            style={{ marginBottom: 12, maxHeight: 220, overflow: 'auto' }}
            dataSource={hits}
            renderItem={(h) => (
              <List.Item
                style={{ cursor: 'pointer' }}
                onClick={() => applyHit(h)}
              >
                <Space>
                  {h.cover_url ? (
                    <img
                      src={h.cover_url}
                      alt=""
                      style={{ width: 36, height: 36, borderRadius: 4, objectFit: 'cover' }}
                    />
                  ) : (
                    <div
                      style={{
                        width: 36,
                        height: 36,
                        borderRadius: 4,
                        background: 'rgba(255,255,255,0.1)',
                      }}
                    />
                  )}
                  <span>{h.title}</span>
                  <Text type="secondary">{h.artist}</Text>
                  {h.album && (
                    <Text type="secondary" style={{ fontSize: 12, opacity: 0.7 }}>
                      · {h.album}
                    </Text>
                  )}
                </Space>
              </List.Item>
            )}
          />
        )}

        <Form.Item label="音频文件（可选，本地 mp3 等；不传则仅元数据/在线音源）">
          <Upload
            fileList={fileList}
            maxCount={1}
            accept=".mp3,.m4a,.flac,.wav,.aac,.ogg"
            beforeUpload={async (file) => {
              try {
                const { data } = await musicApi.uploadAudio(file as File)
                setFileKey(data.file_key)
                setFileList([
                  { uid: '1', name: (file as File).name, status: 'done' },
                ])
                message.success('音频上传成功')
              } catch {
                message.error('音频上传失败')
              }
              return false
            }}
            onRemove={() => {
              setFileKey(null)
              setFileList([])
            }}
          >
            <Button icon={<UploadOutlined />}>选择音频</Button>
          </Upload>
        </Form.Item>
      </Form>
      </Modal>
    </ConfigProvider>
  )
}

// ── 编辑歌曲：改元信息 + 手动微调情绪坐标 ──
function EditSongModal({
  song,
  onClose,
  onDone,
}: {
  song: Song | null
  onClose: () => void
  onDone: () => void
}) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (song) {
      form.setFieldsValue({
        title: song.title,
        artist: song.artist,
        album: song.album,
        valence: song.valence,
        arousal: song.arousal,
        mood_tags: (song.mood_tags ?? []).join('、'),
        lyric: song.lyric,
      })
    }
  }, [song, form])

  const onSubmit = async () => {
    if (!song) return
    const values = await form.validateFields()
    setSubmitting(true)
    try {
      await musicApi.updateSong(song.id, {
        title: values.title,
        artist: values.artist,
        album: values.album,
        valence: Number(values.valence),
        arousal: Number(values.arousal),
        mood_tags: String(values.mood_tags || '')
          .split(/[、,，\s]+/)
          .filter(Boolean),
        lyric: values.lyric,
      })
      message.success('已更新')
      onDone()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <ConfigProvider theme={darkModalTheme}>
      <Modal
        title="编辑歌曲"
        open={!!song}
      onCancel={onClose}
      onOk={onSubmit}
      confirmLoading={submitting}
      destroyOnClose
    >
      <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
        <Form.Item name="title" label="歌名" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item name="artist" label="歌手">
          <Input />
        </Form.Item>
        <Form.Item name="album" label="专辑">
          <Input />
        </Form.Item>
        <Space size="large">
          <Form.Item
            name="valence"
            label="效价 valence (-1~1)"
            tooltip="越大越积极愉悦，越小越消极低落"
          >
            <Input type="number" step={0.1} min={-1} max={1} style={{ width: 140 }} />
          </Form.Item>
          <Form.Item
            name="arousal"
            label="唤醒度 arousal (0~1)"
            tooltip="越大越激昂，越小越舒缓"
          >
            <Input type="number" step={0.1} min={0} max={1} style={{ width: 140 }} />
          </Form.Item>
        </Space>
        <Form.Item name="mood_tags" label="情绪标签（顿号/逗号分隔）">
          <Input placeholder="如：怀旧、清新" />
        </Form.Item>
        <Form.Item name="lyric" label="LRC 歌词（可选）">
          <Input.TextArea rows={4} placeholder="[00:01.00]歌词..." />
        </Form.Item>
      </Form>
      </Modal>
    </ConfigProvider>
  )
}
