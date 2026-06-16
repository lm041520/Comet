import { useEffect, useMemo, useState } from 'react'
import { Button, Card, Col, Empty, Modal, Row, Spin, Tag, Tooltip } from 'antd'
import {
  ArrowRightOutlined,
  BookOutlined,
  CheckCircleFilled,
  CommentOutlined,
  CustomerServiceOutlined,
  DeploymentUnitOutlined,
  HddOutlined,
  PictureOutlined,
  QuestionCircleOutlined,
  RobotOutlined,
  SettingOutlined,
  SmileOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import ReactECharts from 'echarts-for-react'
import {
  dashboardApi,
  type DailyReview,
  type MemoryStatsData,
  type OverviewData,
} from '@/api/dashboard'
import {
  emotionApi,
  type EmotionDistributionItem,
  type EmotionProfile,
  type EmotionTrendPoint,
} from '@/api/emotion'
import { modelApi, type ModelConfigItem } from '@/api/models'
import { useAuthStore } from '@/stores/authStore'

const WELCOME_SEEN_KEY = 'comet_welcome_seen'

export default function HomePage() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const [review, setReview] = useState<DailyReview | null>(null)
  const [overview, setOverview] = useState<OverviewData | null>(null)
  const [memStats, setMemStats] = useState<MemoryStatsData | null>(null)
  const [emotionProfile, setEmotionProfile] = useState<EmotionProfile | null>(null)
  const [emotionTrend, setEmotionTrend] = useState<EmotionTrendPoint[]>([])
  const [emotionDist, setEmotionDist] = useState<EmotionDistributionItem[]>([])
  const [models, setModels] = useState<ModelConfigItem[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [welcomeOpen, setWelcomeOpen] = useState(false)

  // 首次登录弹欢迎引导（localStorage 记忆，只弹一次）
  useEffect(() => {
    if (!localStorage.getItem(WELCOME_SEEN_KEY)) setWelcomeOpen(true)
  }, [])

  const closeWelcome = () => {
    localStorage.setItem(WELCOME_SEEN_KEY, '1')
    setWelcomeOpen(false)
  }

  useEffect(() => {
    let cancelled = false
    let pollTimer: ReturnType<typeof setTimeout> | null = null
    let polls = 0

    const fetchReview = () => {
      dashboardApi
        .dailyReview()
        .then(({ data }) => {
          if (cancelled) return
          setReview(data)
          if (data.generating && polls < 10) {
            polls += 1
            pollTimer = setTimeout(fetchReview, 3000)
          }
        })
        .catch(() => {})
    }

    void (async () => {
      setLoading(true)
      try {
        const [ov, ms] = await Promise.all([
          dashboardApi.overview(),
          dashboardApi.memoryStats(),
        ])
        setOverview(ov.data)
        setMemStats(ms.data)
      } catch {
        // 统计失败不致命
      } finally {
        setLoading(false)
      }
      modelApi
        .list()
        .then(({ data }) => setModels(data))
        .catch(() => setModels([]))
      fetchReview()
      emotionApi
        .current()
        .then(({ data }) => setEmotionProfile(data))
        .catch(() => {})
      emotionApi
        .trend(14)
        .then(({ data }) => setEmotionTrend(data.points))
        .catch(() => {})
      emotionApi
        .distribution(30)
        .then(({ data }) => setEmotionDist(data.items))
        .catch(() => {})
    })()

    return () => {
      cancelled = true
      if (pollTimer) clearTimeout(pollTimer)
    }
  }, [])

  const c = overview?.counts

  // 快速开始：根据已配置模型类型判断完成度
  const modelTypes = useMemo(
    () => new Set((models ?? []).map((m) => m.type)),
    [models],
  )
  const hasChat = modelTypes.has('chat') || modelTypes.has('multimodal')
  const hasEmbedding = modelTypes.has('embedding')
  const hasDocs = (c?.documents ?? 0) > 0
  const hasChatted = (c?.conversations ?? 0) > 0

  const quickSteps = [
    {
      done: hasChat,
      title: '配置对话模型（必做）',
      icon: <SettingOutlined />,
      desc: '先去「模型配置」加一个对话大模型，这是一切功能的基础。推荐智谱 GLM / DeepSeek（注册即送免费额度），配置页里有各家申请入口，把 API Key 填进去、测试通过即可。',
      action: () => navigate('/settings/models'),
      btn: hasChat ? '已配置' : '去配置',
    },
    {
      done: hasEmbedding,
      title: '配置向量模型',
      icon: <SettingOutlined />,
      desc: '再加一个 embedding（向量）模型，知识库和记忆的语义检索靠它。同样在「模型配置」里添加。',
      action: () => navigate('/settings/models'),
      btn: hasEmbedding ? '已配置' : '去配置',
    },
    {
      done: hasDocs,
      title: '建立你的知识库（可选）',
      icon: <BookOutlined />,
      desc: '上传文档或导入网页，系统自动分块、向量化、打标签，之后 AI 回答会自动引用你的资料。',
      action: () => navigate('/knowledge'),
      btn: hasDocs ? '去管理' : '去上传',
    },
    {
      done: hasChatted,
      title: '开始智能对话',
      icon: <CommentOutlined />,
      desc: '配好对话模型就能直接聊。AI 会自动调用知识库、记忆、联网工具回答，并在对话后沉淀记忆，越用越懂你。',
      action: () => navigate('/chat'),
      btn: hasChatted ? '继续对话' : '去对话',
    },
  ]

  // 功能导航
  const features = [
    { icon: <CommentOutlined />, label: '智能对话', desc: 'Agent 工具编排问答', to: '/chat', color: '#155EEF' },
    { icon: <BookOutlined />, label: '知识库', desc: '文档/网页 RAG 检索', to: '/knowledge', color: '#369F21' },
    { icon: <HddOutlined />, label: '记忆图谱', desc: '实体关系与画像', to: '/memory', color: '#7C4DFF' },
    { icon: <DeploymentUnitOutlined />, label: '图谱可视化', desc: '关系网络与时间线', to: '/graph', color: '#FF8A34' },
    { icon: <RobotOutlined />, label: '角色配置', desc: '人设与对话偏好', to: '/settings/agent', color: '#13C2C2' },
    { icon: <CustomerServiceOutlined />, label: '情绪音乐', desc: '随心情推荐歌单', to: '/music', color: '#EB2F96' },
  ]

  const pieOption = {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0, type: 'scroll' },
    series: [
      {
        type: 'pie',
        radius: ['42%', '70%'],
        center: ['50%', '44%'],
        data: overview?.tag_distribution ?? [],
        label: { show: false },
        itemStyle: { borderColor: '#fff', borderWidth: 2 },
      },
    ],
  }

  const lineOption = {
    tooltip: { trigger: 'axis' },
    grid: { left: 36, right: 16, top: 24, bottom: 28 },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: (memStats?.trend ?? []).map((t) => t.date.slice(5)),
    },
    yAxis: { type: 'value', minInterval: 1 },
    series: [
      {
        type: 'line',
        smooth: true,
        data: (memStats?.trend ?? []).map((t) => t.count),
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(21,94,239,0.35)' },
              { offset: 1, color: 'rgba(21,94,239,0.02)' },
            ],
          },
        },
        lineStyle: { width: 3 },
        itemStyle: { color: '#155EEF' },
      },
    ],
  }

  const emotionTrendOption = {
    tooltip: { trigger: 'axis' },
    legend: { data: ['情绪倾向', '情绪强度'], top: 0 },
    grid: { left: 36, right: 16, top: 32, bottom: 28 },
    xAxis: {
      type: 'category',
      data: emotionTrend.map((t) => t.date.slice(5)),
    },
    yAxis: { type: 'value', min: -1, max: 1 },
    series: [
      {
        name: '情绪倾向',
        type: 'line',
        smooth: true,
        connectNulls: true,
        data: emotionTrend.map((t) => (t.count > 0 ? t.avg_valence : null)),
        itemStyle: { color: '#369F21' },
        areaStyle: { opacity: 0.1 },
      },
      {
        name: '情绪强度',
        type: 'line',
        smooth: true,
        connectNulls: true,
        data: emotionTrend.map((t) => (t.count > 0 ? t.avg_arousal : null)),
        itemStyle: { color: '#FF8A34' },
      },
    ],
  }

  const emotionPieOption = {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0, type: 'scroll' },
    series: [
      {
        type: 'pie',
        radius: ['42%', '70%'],
        center: ['50%', '44%'],
        data: emotionDist,
        label: { show: false },
        itemStyle: { borderColor: '#fff', borderWidth: 2 },
      },
    ],
  }

  const hasEmotion = (emotionProfile?.sample_count ?? 0) > 0
  const allReady = hasChat && hasEmbedding
  const finishedSteps = quickSteps.filter((s) => s.done).length
  // 基础没配好（缺对话或向量模型）= 新用户态：首屏聚焦引导、隐藏空数据
  // models 还没加载完（null）时不判定为新用户，避免闪现
  const needsSetup = models !== null && !allReady

  // 数据概览 KPI 卡片（情绪指数若有则置顶）
  const healthIndex = emotionProfile?.health_index ?? 0
  const healthColor =
    healthIndex >= 60 ? '#369F21' : healthIndex >= 40 ? '#FF8A34' : '#FF5D34'
  const kpis = [
    ...(hasEmotion
      ? [{ label: '情绪指数', value: healthIndex, icon: <SmileOutlined />, color: healthColor }]
      : []),
    { label: '文档', value: c?.documents ?? 0, icon: <BookOutlined />, color: '#369F21' },
    { label: '图片', value: c?.images ?? 0, icon: <PictureOutlined />, color: '#FF8A34' },
    { label: '对话', value: c?.conversations ?? 0, icon: <CommentOutlined />, color: '#155EEF' },
    { label: '记忆实体', value: c?.entities ?? 0, icon: <HddOutlined />, color: '#7C4DFF' },
    { label: '记忆社区', value: c?.communities ?? 0, icon: <DeploymentUnitOutlined />, color: '#EB2F96' },
  ]

  // ── 各区块抽成元素，按「新用户态 / 常用态」组合 ──

  const welcomeModal = (
    <Modal
      open={welcomeOpen}
      onCancel={closeWelcome}
      centered
      width={460}
      footer={null}
      title={null}
    >
      <div style={{ textAlign: 'center', padding: '8px 4px' }}>
        <div style={{ fontSize: 34, marginBottom: 6 }}>👋</div>
        <h2 style={{ margin: '0 0 8px', fontSize: 22 }}>欢迎使用彗记 Comet</h2>
        <p style={{ color: '#475467', lineHeight: 1.85, margin: '0 0 14px' }}>
          这是你的个人 AI 知识库 + 记忆助手：和 AI 对话、把文档/网页存进知识库让它引用、
          它还会自动记住你聊过的事，越用越懂你。
        </p>
        <div
          style={{
            background: '#F2F7FF',
            border: '1px solid #DBE7FF',
            borderRadius: 12,
            padding: '12px 16px',
            textAlign: 'left',
            color: '#1D2129',
            lineHeight: 1.8,
            marginBottom: 18,
          }}
        >
          <b>开始前只需一步：</b>配置一个大模型 API。
          <br />
          推荐 <b>智谱 GLM</b> 或 <b>DeepSeek</b>（注册即送免费额度），
          在「模型配置」页填入 API Key 即可。
        </div>
        <div style={{ display: 'flex', gap: 10, justifyContent: 'center' }}>
          <Button
            type="primary"
            size="large"
            onClick={() => {
              closeWelcome()
              navigate('/settings/models')
            }}
          >
            去配置模型
          </Button>
          <Button size="large" onClick={closeWelcome}>
            先随便逛逛
          </Button>
        </div>
      </div>
    </Modal>
  )

  const quickStartCard = (
    <Card
      style={{ marginBottom: 22, borderRadius: 16 }}
      styles={{ body: { padding: 22 } }}
      title={
        <span>
          🚀 {needsSetup ? '开始使用彗记' : '快速开始'}
          <span style={{ color: '#98A2B3', fontWeight: 400, fontSize: 13, marginLeft: 10 }}>
            {finishedSteps}/{quickSteps.length} 已完成
          </span>
        </span>
      }
      extra={
        allReady ? (
          <Tag color="success" icon={<CheckCircleFilled />}>
            基础配置已就绪
          </Tag>
        ) : (
          <Tag color="warning">第一步：先配置对话模型</Tag>
        )
      }
    >
      {needsSetup && (
        <p style={{ margin: '0 0 16px', color: '#475467', lineHeight: 1.8 }}>
          完成下面几步，就能开始和你的 AI 助手对话啦 👇 其中{' '}
          <b style={{ color: '#155EEF' }}>配置对话模型是必做项</b>，没配好其他功能都用不了。
        </p>
      )}
      <Row gutter={[14, 14]}>
        {quickSteps.map((step, i) => {
          // 高亮"当前应做"的第一个未完成步骤
          const firstTodo = quickSteps.findIndex((s) => !s.done)
          const isCurrent = !step.done && i === firstTodo
          return (
            <Col xs={24} sm={12} lg={6} key={step.title}>
              <div
                className={`qs-step${step.done ? ' qs-step--done' : ''}`}
                style={
                  isCurrent
                    ? { borderColor: '#155EEF', boxShadow: '0 0 0 2px rgba(21,94,239,0.12)' }
                    : undefined
                }
              >
                <div className="qs-step__num">
                  {step.done ? <CheckCircleFilled /> : i + 1}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column' }}>
                  <div className="qs-step__title">
                    {step.icon} {step.title}
                  </div>
                  <div className="qs-step__desc">{step.desc}</div>
                  <Button
                    type={step.done ? 'default' : 'primary'}
                    size="small"
                    style={{ marginTop: 10, alignSelf: 'flex-start' }}
                    onClick={step.action}
                  >
                    {step.btn} <ArrowRightOutlined />
                  </Button>
                </div>
              </div>
            </Col>
          )
        })}
      </Row>
    </Card>
  )

  const featuresCard = (
    <Card
      title="✨ 功能一览"
      style={{ marginBottom: 22, borderRadius: 16 }}
      styles={{ body: { padding: 18 } }}
    >
      <Row gutter={[14, 14]}>
        {features.map((f) => (
          <Col xs={12} sm={8} md={8} lg={4} key={f.label}>
            <div
              className="qs-step"
              style={{ cursor: 'pointer', alignItems: 'center' }}
              onClick={() => navigate(f.to)}
            >
              <div
                className="stat-card__icon"
                style={{ background: `${f.color}1a`, color: f.color, marginBottom: 0 }}
              >
                {f.icon}
              </div>
              <div>
                <div className="qs-step__title">{f.label}</div>
                <div className="qs-step__desc" style={{ marginTop: 2 }}>
                  {f.desc}
                </div>
              </div>
            </div>
          </Col>
        ))}
      </Row>
    </Card>
  )

  const reviewCard = (
    <Card
      title="📅 今日回顾"
      style={{ marginBottom: 22, borderRadius: 16 }}
      extra={
        review?.stats && (
          <span style={{ color: '#98A2B3', fontSize: 13 }}>
            对话 {review.stats.messages} · 记忆 {review.stats.memories} · 文档{' '}
            {review.stats.documents}
            {review.stats.songs ? ` · 听歌 ${review.stats.songs}` : ''}
          </span>
        )
      }
    >
      <p style={{ margin: 0, color: '#475467', lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>
        {review?.content ?? '加载中…'}
      </p>
      {review?.generating && (
        <div style={{ marginTop: 8, color: '#98A2B3', fontSize: 12 }}>
          <Spin size="small" style={{ marginRight: 6 }} />
          正在生成今日回顾…
        </div>
      )}
      {review?.care && (
        <div className="daily-care">
          <span className="daily-care-text">💛 {review.care}</span>
          <Button
            size="small"
            type="primary"
            ghost
            icon={<CommentOutlined />}
            onClick={() =>
              navigate(`/chat?greeting=${encodeURIComponent(review.care ?? '')}`)
            }
          >
            聊聊
          </Button>
        </div>
      )}
    </Card>
  )

  const dataSection = (
    <>
      <div className="dash-section-title">📊 数据概览</div>
      {loading ? (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin />
        </div>
      ) : (
        <div className="dash-kpi-grid">
          {kpis.map((k) => (
            <div className="stat-card" key={k.label}>
              <div className="stat-card__bar" style={{ background: k.color }} />
              <div
                className="stat-card__icon"
                style={{ background: `${k.color}1a`, color: k.color }}
              >
                {k.icon}
              </div>
              <div className="stat-card__value">{k.value}</div>
              <div className="stat-card__label">{k.label}</div>
            </div>
          ))}
        </div>
      )}

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} md={12}>
          <Card title="知识库分类分布" style={{ borderRadius: 16 }}>
            {loading ? (
              <div style={{ textAlign: 'center', padding: 40 }}>
                <Spin />
              </div>
            ) : overview?.tag_distribution.length ? (
              <ReactECharts option={pieOption} style={{ height: 280 }} />
            ) : (
              <Empty description="还没有分类标签" />
            )}
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card title="近 14 天记忆新增" style={{ borderRadius: 16 }}>
            {memStats?.trend.length ? (
              <ReactECharts option={lineOption} style={{ height: 280 }} />
            ) : (
              <Empty description="暂无记忆数据" />
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} md={12}>
          <Card
            title={
              <span>
                近 14 天情绪趋势
                <Tooltip title="情绪倾向：越高越积极开心、越低越消极低落（范围 -1~1）；情绪强度：越高情绪越激动强烈、越低越平静（范围 -1~1）。由 AI 从你的对话中感知。">
                  <QuestionCircleOutlined style={{ marginLeft: 6, color: '#98a2b3', fontSize: 13 }} />
                </Tooltip>
              </span>
            }
            style={{ borderRadius: 16 }}
          >
            {hasEmotion ? (
              <ReactECharts option={emotionTrendOption} style={{ height: 280 }} />
            ) : (
              <Empty description="多聊几句，AI 会感知你的情绪" />
            )}
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card title="近 30 天情绪分布" style={{ borderRadius: 16 }}>
            {emotionDist.length ? (
              <ReactECharts option={emotionPieOption} style={{ height: 280 }} />
            ) : (
              <Empty description="暂无情绪数据" />
            )}
          </Card>
        </Col>
      </Row>
    </>
  )

  return (
    <div className="fluid-page">
      {welcomeModal}

      {/* 欢迎横幅 */}
      <div className="dash-hero">
        <h2 className="dash-hero__title">
          你好，{user?.nickname || user?.username || '朋友'} 👋
        </h2>
        <p className="dash-hero__sub">
          {needsSetup
            ? '只差一步就能开始：先配置一个对话大模型，下面有详细引导。'
            : '欢迎使用彗记 Comet —— 你的个人 AI 知识库与记忆助手。让 AI 记住你、读懂你的资料。'}
        </p>
      </div>

      {needsSetup ? (
        // 新用户态：聚焦引导，隐藏空的数据看板
        <>
          {quickStartCard}
          {featuresCard}
        </>
      ) : (
        // 常用态：完整面板（已全部完成则不再显示引导卡）
        <>
          {reviewCard}
          {finishedSteps < quickSteps.length && quickStartCard}
          {featuresCard}
          {dataSection}
        </>
      )}
    </div>
  )
}
