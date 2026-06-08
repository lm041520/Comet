import { Avatar, Button, Drawer, Dropdown, Input, Layout, Menu, Space, message } from 'antd'
import {
  AppstoreOutlined,
  BookOutlined,
  CommentOutlined,
  CustomerServiceOutlined,
  DeploymentUnitOutlined,
  HddOutlined,
  HistoryOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PictureOutlined,
  PlusOutlined,
  RobotOutlined,
  SearchOutlined,
  SettingOutlined,
  StarOutlined,
  ToolOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { useEffect, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import { useChatHeaderStore } from '@/stores/chatHeaderStore'
import { AuthenticatedImage } from '@/components/AuthenticatedImage'
import MusicPlayer from '@/components/MusicPlayer'
import logo from '@/images/logo.png'

const { Sider, Content, Header } = Layout

// 分组导航：按职责归类，分组标题灰色小字，更清晰
const menuItems = [
  {
    type: 'group' as const,
    label: '工作台',
    children: [
      { key: '/', icon: <AppstoreOutlined />, label: '仪表盘' },
      { key: '/chat', icon: <CommentOutlined />, label: '对话' },
    ],
  },
  {
    type: 'group' as const,
    label: '知识与记忆',
    children: [
      { key: '/knowledge', icon: <BookOutlined />, label: '知识库' },
      { key: '/images', icon: <PictureOutlined />, label: '图片库' },
      { key: '/memory', icon: <HddOutlined />, label: '记忆' },
      { key: '/graph', icon: <DeploymentUnitOutlined />, label: '知识图谱' },
      { key: '/music', icon: <CustomerServiceOutlined />, label: '音乐' },
    ],
  },
  {
    type: 'group' as const,
    label: '检索与收藏',
    children: [
      { key: '/search', icon: <SearchOutlined />, label: '全局搜索' },
      { key: '/favorites', icon: <StarOutlined />, label: '收藏夹' },
    ],
  },
  {
    type: 'group' as const,
    label: '设置',
    children: [
      { key: '/settings/models', icon: <SettingOutlined />, label: '模型配置' },
      { key: '/settings/agent', icon: <RobotOutlined />, label: 'Agent 配置' },
      { key: '/settings/tools', icon: <ToolOutlined />, label: '工具配置' },
    ],
  },
]

// 小屏（手机/窄平板）检测：≤768px 走抽屉式侧边栏
function useIsMobile() {
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== 'undefined' && window.innerWidth <= 768,
  )
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 768px)')
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])
  return isMobile
}

export default function MainLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const isMobile = useIsMobile()
  // 聊天页注册的顶栏操作（手机端聊天页用它替代搜索框，合并成一行）
  const chatHeaderActive = useChatHeaderStore((s) => s.active)
  const chatOpenHistory = useChatHeaderStore((s) => s.openHistory)
  const chatNewChat = useChatHeaderStore((s) => s.newChat)
  const showChatHeader = isMobile && chatHeaderActive && location.pathname === '/chat'

  // 桌面端：侧边栏折叠（窄条）；移动端：抽屉开关
  const [collapsed, setCollapsed] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)

  // 切换路由后自动关闭移动端抽屉
  useEffect(() => {
    setDrawerOpen(false)
  }, [location.pathname])

  // 音乐页沉浸式深色主题：进入 /music 整体变深色霓虹，离开自动恢复
  const immersive = location.pathname === '/music'

  const onLogout = async () => {
    await logout()
    message.success('已退出登录')
    navigate('/login', { replace: true })
  }

  // logo 头部（桌面 Sider 与移动抽屉共用）
  const brand = (mini: boolean) => (
    <div
      style={{
        height: 64,
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        paddingInline: mini ? 0 : 20,
        justifyContent: mini ? 'center' : 'flex-start',
        color: immersive ? '#fff' : '#171719',
        overflow: 'hidden',
      }}
    >
      <img
        src={logo}
        alt="彗记"
        style={{ width: 36, height: 36, borderRadius: 9, objectFit: 'cover', flexShrink: 0 }}
      />
      {!mini && (
        <span style={{ fontWeight: 600, fontSize: 19, whiteSpace: 'nowrap' }}>彗记 Comet</span>
      )}
    </div>
  )

  const navMenu = (mini: boolean) => (
    <Menu
      mode="inline"
      theme={immersive ? 'dark' : 'light'}
      inlineCollapsed={mini}
      selectedKeys={[location.pathname]}
      items={menuItems}
      onClick={({ key }) => navigate(key)}
      style={{ borderInlineEnd: 'none', background: 'transparent' }}
    />
  )

  return (
    <Layout style={{ height: '100%' }} className={immersive ? 'immersive-layout' : ''}>
      {/* 桌面端：常驻可折叠侧边栏 */}
      {!isMobile && (
        <Sider
          width={236}
          collapsible
          collapsed={collapsed}
          trigger={null}
          collapsedWidth={72}
          style={{
            display: 'flex',
            flexDirection: 'column',
            borderInlineEnd: immersive
              ? '1px solid rgba(255,255,255,0.08)'
              : '1px solid #f0f0f0',
            background: immersive
              ? 'linear-gradient(180deg, #141633 0%, #0c0d18 100%)'
              : undefined,
            transition: 'background 0.4s',
          }}
        >
          {brand(collapsed)}
          <div style={{ flex: 1, overflowY: 'auto', paddingBottom: 12 }}>{navMenu(collapsed)}</div>
        </Sider>
      )}

      {/* 移动端：抽屉式侧边栏 */}
      {isMobile && (
        <Drawer
          placement="left"
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          width={236}
          closable={false}
          styles={{
            body: { padding: 0 },
            content: immersive
              ? { background: 'linear-gradient(180deg, #141633 0%, #0c0d18 100%)' }
              : undefined,
          }}
        >
          {brand(false)}
          <div style={{ overflowY: 'auto', paddingBottom: 12 }}>{navMenu(false)}</div>
        </Drawer>
      )}

      <Layout style={{ background: immersive ? '#0b0c16' : undefined, transition: 'background 0.4s' }}>
        <Header
          style={{
            paddingInline: isMobile ? 12 : 24,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 8,
            borderBottom: immersive
              ? '1px solid rgba(255,255,255,0.08)'
              : '1px solid #f0f0f0',
            background: immersive ? 'rgba(18,20,40,0.8)' : undefined,
            backdropFilter: immersive ? 'blur(10px)' : undefined,
            transition: 'background 0.4s',
          }}
        >
          <div style={{ flexShrink: 0, display: 'flex', alignItems: 'center' }}>
            <Button
              type="text"
              aria-label="菜单"
              icon={
                isMobile ? (
                  <MenuUnfoldOutlined />
                ) : collapsed ? (
                  <MenuUnfoldOutlined />
                ) : (
                  <MenuFoldOutlined />
                )
              }
              onClick={() =>
                isMobile ? setDrawerOpen(true) : setCollapsed((c) => !c)
              }
              style={{ color: immersive ? '#fff' : undefined, fontSize: 18 }}
            />
          </div>

          {/* 中间区：手机端聊天页显示「会话 / 新对话」，其余页面显示搜索框 */}
          {showChatHeader ? (
            <div
              style={{
                flex: 1,
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'center',
                gap: 8,
                minWidth: 0,
                padding: '0 8px',
              }}
            >
              <Button
                type="text"
                icon={<HistoryOutlined />}
                onClick={() => chatOpenHistory?.()}
              >
                会话
              </Button>
              <Button
                type="text"
                icon={<PlusOutlined />}
                onClick={() => chatNewChat?.()}
              >
                新对话
              </Button>
            </div>
          ) : (
            <div
              style={{
                flex: 1,
                display: 'flex',
                justifyContent: 'center',
                minWidth: 0,
                padding: isMobile ? '0 8px' : '0 16px',
              }}
            >
              <Input
                className={`top-search${immersive ? ' top-search--dark' : ''}`}
                prefix={<SearchOutlined style={{ color: '#98A2B3' }} />}
                placeholder={isMobile ? '搜索…' : '搜索文档、图片、记忆…'}
                allowClear
                style={{ width: '100%', maxWidth: 560 }}
                onPressEnter={(e) => {
                  const q = (e.target as HTMLInputElement).value.trim()
                  if (q) navigate(`/search?q=${encodeURIComponent(q)}`)
                }}
              />
            </div>
          )}

          <Dropdown
            menu={{
              items: [
                {
                  key: 'profile',
                  icon: <UserOutlined />,
                  label: '个人中心',
                  onClick: () => navigate('/profile'),
                },
                { type: 'divider' },
                {
                  key: 'logout',
                  icon: <LogoutOutlined />,
                  label: '退出登录',
                  onClick: onLogout,
                },
              ],
            }}
          >
            <Space align="center" style={{ cursor: 'pointer', flexShrink: 0 }}>
              {user?.avatar ? (
                <AuthenticatedImage
                  src={user.avatar}
                  alt="头像"
                  style={{
                    width: 30,
                    height: 30,
                    borderRadius: '50%',
                    objectFit: 'cover',
                    display: 'block',
                  }}
                />
              ) : (
                <Avatar size={30} style={{ background: '#155EEF' }}>
                  {user?.username?.[0]?.toUpperCase() ?? <UserOutlined />}
                </Avatar>
              )}
              {!isMobile && (
                <span style={{ fontWeight: 500, color: immersive ? '#fff' : undefined }}>
                  {user?.nickname || user?.username || '用户'}
                </span>
              )}
            </Space>
          </Dropdown>
        </Header>
        <Content style={{ padding: isMobile ? 14 : 24, overflow: 'auto' }}>
          <Outlet />
        </Content>
      </Layout>
      <MusicPlayer />
    </Layout>
  )
}
