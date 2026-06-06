import { Avatar, Dropdown, Input, Layout, Menu, Space, message } from 'antd'
import {
  AppstoreOutlined,
  BookOutlined,
  CommentOutlined,
  DeploymentUnitOutlined,
  HddOutlined,
  LogoutOutlined,
  PictureOutlined,
  RobotOutlined,
  SearchOutlined,
  SettingOutlined,
  StarOutlined,
  ToolOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
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

export default function MainLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)

  const onLogout = async () => {
    await logout()
    message.success('已退出登录')
    navigate('/login', { replace: true })
  }

  return (
    <Layout style={{ height: '100vh' }}>
      <Sider
        width={236}
        style={{
          display: 'flex',
          flexDirection: 'column',
          borderInlineEnd: '1px solid #f0f0f0',
        }}
      >
        <div
          style={{
            height: 64,
            flexShrink: 0,
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            paddingInline: 20,
            color: '#171719',
          }}
        >
          <img
            src={logo}
            alt="彗记"
            style={{ width: 36, height: 36, borderRadius: 9, objectFit: 'cover' }}
          />
          <span style={{ fontWeight: 600, fontSize: 19 }}>彗记 Comet</span>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', paddingBottom: 12 }}>
          <Menu
            mode="inline"
            selectedKeys={[location.pathname]}
            items={menuItems}
            onClick={({ key }) => navigate(key)}
            style={{ borderInlineEnd: 'none' }}
          />
        </div>
      </Sider>
      <Layout>
        <Header
          style={{
            paddingInline: 24,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: '1px solid #f0f0f0',
          }}
        >
          <Input.Search
            placeholder="搜索文档、图片、记忆…"
            allowClear
            style={{ maxWidth: 420, width: '40vw' }}
            onSearch={(v) => {
              const q = v.trim()
              if (q) navigate(`/search?q=${encodeURIComponent(q)}`)
            }}
          />
          <Dropdown
            menu={{
              items: [
                {
                  key: 'logout',
                  icon: <LogoutOutlined />,
                  label: '退出登录',
                  onClick: onLogout,
                },
              ],
            }}
          >
            <Space style={{ cursor: 'pointer' }}>
              <Avatar size={30} style={{ background: '#155EEF' }}>
                {user?.username?.[0]?.toUpperCase() ?? <UserOutlined />}
              </Avatar>
              <span style={{ fontWeight: 500 }}>{user?.username ?? '用户'}</span>
            </Space>
          </Dropdown>
        </Header>
        <Content style={{ padding: 24, overflow: 'auto' }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
