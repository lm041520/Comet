import { useEffect, useState } from 'react'
import { Alert, Badge, Button, Card, Col, Row, Spin, Statistic } from 'antd'
import {
  CheckCircleTwoTone,
  CloudServerOutlined,
  DatabaseOutlined,
  DeploymentUnitOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import client from '@/api/client'
import { useAuthStore } from '@/stores/authStore'

interface HealthData {
  healthy: boolean
  checks: Record<string, boolean>
}

const STORE_META: Record<string, { label: string; icon: React.ReactNode }> = {
  postgres: { label: 'PostgreSQL', icon: <DatabaseOutlined /> },
  elasticsearch: { label: 'Elasticsearch', icon: <CloudServerOutlined /> },
  neo4j: { label: 'Neo4j', icon: <DeploymentUnitOutlined /> },
  redis: { label: 'Redis', icon: <ThunderboltOutlined /> },
}

export default function HomePage() {
  const user = useAuthStore((s) => s.user)
  const [health, setHealth] = useState<HealthData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const check = async () => {
    setLoading(true)
    setError(null)
    try {
      const hb = await client.get<unknown, { data: HealthData }>('/health')
      setHealth(hb.data)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    check()
  }, [])

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      {/* 欢迎横幅 */}
      <Card
        style={{
          marginBottom: 24,
          background: 'linear-gradient(120deg, #171719 0%, #1d2b53 100%)',
          border: 'none',
        }}
        styles={{ body: { padding: '28px 32px' } }}
      >
        <h2 style={{ color: '#fff', margin: 0, fontSize: 24 }}>
          你好，{user?.username ?? '朋友'} 👋
        </h2>
        <p style={{ color: 'rgba(255,255,255,0.7)', marginTop: 8, marginBottom: 0 }}>
          欢迎使用彗记 Comet —— 你的个人 AI 知识库与记忆助手。
        </p>
      </Card>

      {/* 系统状态 */}
      <Card
        title="系统状态"
        extra={
          <Button icon={<ReloadOutlined />} onClick={check} loading={loading}>
            刷新
          </Button>
        }
      >
        {loading && (
          <div style={{ textAlign: 'center', padding: 24 }}>
            <Spin />
          </div>
        )}
        {error && (
          <Alert type="error" message="无法连接后端" description={error} showIcon />
        )}
        {health && !loading && (
          <>
            <Alert
              style={{ marginBottom: 20 }}
              type={health.healthy ? 'success' : 'warning'}
              showIcon
              message={
                health.healthy ? '所有存储服务运行正常' : '部分存储服务未就绪'
              }
            />
            <Row gutter={[16, 16]}>
              {Object.entries(health.checks).map(([name, ok]) => {
                const meta = STORE_META[name] ?? { label: name, icon: null }
                return (
                  <Col xs={12} sm={12} md={6} key={name}>
                    <Card size="small" styles={{ body: { padding: 16 } }}>
                      <Statistic
                        title={
                          <span style={{ color: '#667085' }}>
                            {meta.icon} {meta.label}
                          </span>
                        }
                        valueRender={() => (
                          <Badge
                            status={ok ? 'success' : 'error'}
                            text={
                              <span style={{ fontSize: 15 }}>
                                {ok ? '已连接' : '未就绪'}
                              </span>
                            }
                          />
                        )}
                      />
                    </Card>
                  </Col>
                )
              })}
            </Row>
          </>
        )}
      </Card>

      {/* 占位：后续阶段填充统计 */}
      <Row gutter={[16, 16]} style={{ marginTop: 24 }}>
        {['知识库文档', '图片素材', '记忆条目'].map((t) => (
          <Col xs={24} sm={8} key={t}>
            <Card>
              <Statistic
                title={t}
                value={0}
                prefix={<CheckCircleTwoTone twoToneColor="#155EEF" />}
              />
              <span style={{ color: '#A8A9AA', fontSize: 12 }}>
                功能开发中，敬请期待
              </span>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  )
}
