import { useEffect, useRef, useState } from 'react'
import { Button, Checkbox, Form, Input, Tabs, message } from 'antd'
import { LockOutlined, MailOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import ParticleField from './auth/ParticleField'

interface FormValues {
  email: string
  password: string
}

const LS_REMEMBER = 'comet_remember'

export default function LoginPage() {
  const navigate = useNavigate()
  const login = useAuthStore((s) => s.login)
  const register = useAuthStore((s) => s.register)
  const [tab, setTab] = useState('login')
  const [loading, setLoading] = useState(false)
  const [loginForm] = Form.useForm()
  const [rememberAccount, setRememberAccount] = useState(true)
  const [rememberPassword, setRememberPassword] = useState(false)
  const cardRef = useRef<HTMLDivElement>(null)

  // 进入页面回填记住的账号/密码
  useEffect(() => {
    try {
      const raw = localStorage.getItem(LS_REMEMBER)
      if (!raw) return
      const saved = JSON.parse(raw) as { email?: string; password?: string }
      if (saved.email) {
        loginForm.setFieldsValue({ email: saved.email, password: saved.password ?? '' })
        setRememberAccount(true)
        setRememberPassword(!!saved.password)
      }
    } catch {
      // 回填失败忽略
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 鼠标视差：卡片随鼠标轻微倾斜
  const onMouseMove = (e: React.MouseEvent) => {
    const card = cardRef.current
    if (!card) return
    const rect = card.getBoundingClientRect()
    const cx = rect.left + rect.width / 2
    const cy = rect.top + rect.height / 2
    const dx = (e.clientX - cx) / rect.width
    const dy = (e.clientY - cy) / rect.height
    card.style.transform = `perspective(900px) rotateY(${dx * 6}deg) rotateX(${-dy * 6}deg)`
  }
  const onMouseLeave = () => {
    const card = cardRef.current
    if (card) card.style.transform = 'perspective(900px) rotateY(0) rotateX(0)'
  }

  const onLogin = async (v: FormValues) => {
    setLoading(true)
    try {
      await login(v.email.trim(), v.password)
      // 记住账号/密码
      if (rememberAccount) {
        localStorage.setItem(
          LS_REMEMBER,
          JSON.stringify({
            email: v.email.trim(),
            password: rememberPassword ? v.password : undefined,
          }),
        )
      } else {
        localStorage.removeItem(LS_REMEMBER)
      }
      message.success('登录成功')
      navigate('/', { replace: true })
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const onRegister = async (v: FormValues) => {
    setLoading(true)
    try {
      await register(v.email.trim(), v.password)
      message.success('注册成功，请登录')
      setTab('login')
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const renderForm = (
    onFinish: (v: FormValues) => void,
    submitText: string,
    isLogin: boolean,
  ) => (
    <Form
      form={isLogin ? loginForm : undefined}
      layout="vertical"
      onFinish={onFinish}
      disabled={loading}
      requiredMark={false}
      size="large"
    >
      <Form.Item
        name="email"
        validateTrigger="onBlur"
        rules={[
          { required: true, message: '请输入邮箱' },
          { type: 'email', message: '邮箱格式不正确' },
        ]}
      >
        <Input
          prefix={<MailOutlined />}
          placeholder="邮箱"
          autoComplete="email"
          allowClear
        />
      </Form.Item>
      <Form.Item
        name="password"
        rules={[
          { required: true, message: '请输入密码' },
          { min: 6, message: '密码不能少于 6 位' },
        ]}
      >
        <Input.Password
          prefix={<LockOutlined />}
          placeholder="密码（至少 6 位）"
          autoComplete={tab === 'login' ? 'current-password' : 'new-password'}
        />
      </Form.Item>
      {tab === 'register' && (
        <Form.Item
          name="confirm"
          dependencies={['password']}
          rules={[
            { required: true, message: '请再次输入密码' },
            ({ getFieldValue }) => ({
              validator(_, value) {
                if (!value || getFieldValue('password') === value) {
                  return Promise.resolve()
                }
                return Promise.reject(new Error('两次输入的密码不一致'))
              },
            }),
          ]}
        >
          <Input.Password
            prefix={<LockOutlined />}
            placeholder="确认密码"
            autoComplete="new-password"
          />
        </Form.Item>
      )}
      {isLogin && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 16,
            marginBottom: 12,
            flexWrap: 'wrap',
          }}
        >
          <Checkbox
            checked={rememberAccount}
            onChange={(e) => {
              setRememberAccount(e.target.checked)
              if (!e.target.checked) setRememberPassword(false)
            }}
            style={{ color: 'rgba(255,255,255,0.8)' }}
          >
            记住账号
          </Checkbox>
          <Checkbox
            checked={rememberPassword}
            disabled={!rememberAccount}
            onChange={(e) => setRememberPassword(e.target.checked)}
            style={{ color: 'rgba(255,255,255,0.8)' }}
          >
            记住密码
          </Checkbox>
        </div>
      )}
      <Form.Item style={{ marginBottom: 0, marginTop: 4 }}>
        <Button
          type="primary"
          htmlType="submit"
          block
          size="large"
          loading={loading}
          style={{ height: 46, fontSize: 16, fontWeight: 600 }}
        >
          {submitText}
        </Button>
      </Form.Item>
    </Form>
  )

  return (
    <div
      className="auth-full auth-hero"
      onMouseMove={onMouseMove}
      onMouseLeave={onMouseLeave}
    >
      {/* 漂浮霓虹光球 */}
      <div className="auth-orb o1" />
      <div className="auth-orb o2" />
      <div className="auth-orb o3" />

      {/* 跟随鼠标的粒子层 */}
      <ParticleField />

      {/* 居中玻璃表单卡 */}
      <div className="auth-card" ref={cardRef}>
        <div className="auth-card-glow" />

        {/* 品牌头 */}
        <div style={{ textAlign: 'center', marginBottom: 22 }}>
          <div
            className="auth-logo-badge"
            style={{ margin: '0 auto 14px' }}
          >
            彗
          </div>
          <div style={{ fontSize: 24, fontWeight: 700, letterSpacing: 1 }}>
            彗记 Comet
          </div>
          <div
            style={{
              fontSize: 13,
              color: 'rgba(255,255,255,0.6)',
              marginTop: 6,
            }}
          >
            {tab === 'login'
              ? '欢迎回来，登录以继续'
              : '创建账号，开启你的 AI 知识库'}
          </div>
        </div>

        <Tabs
          activeKey={tab}
          onChange={setTab}
          centered
          items={[
            { key: 'login', label: '登录', children: renderForm(onLogin, '登录', true) },
            {
              key: 'register',
              label: '注册',
              children: renderForm(onRegister, '注册', false),
            },
          ]}
        />

        <div
          style={{
            display: 'flex',
            gap: 8,
            justifyContent: 'center',
            marginTop: 18,
            flexWrap: 'wrap',
          }}
        >
          {['知识库', '记忆图谱', '智能问答', '情绪音乐'].map((t) => (
            <span
              key={t}
              style={{
                padding: '3px 10px',
                borderRadius: 999,
                fontSize: 11,
                color: 'rgba(255,255,255,0.7)',
                background: 'rgba(255,255,255,0.08)',
                border: '1px solid rgba(255,255,255,0.14)',
              }}
            >
              {t}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}
