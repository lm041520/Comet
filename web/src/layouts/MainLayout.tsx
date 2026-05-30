import { Avatar, Dropdown, Layout, Menu, Space, message } from 'antd'
import {
  AppstoreOutlined,
  BookOutlined,
  CommentOutlined,
  DeploymentUnitOutlined,
  HddOutlined,
  LogoutOutlined,
  SettingOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'

const { Sider, Content, Header } = Layout

// 导航骨架：菜单项随各阶段页面落地逐步启用
const menuItems = [
  { key: '/', icon: <AppstoreOutlined />, label: '仪表盘' },
  { key: '/chat', icon: <CommentOutlined />, label: '对话' },
  { key: '/knowledge', icon: <BookOutlined />, label: '知识库' },
  { key: '/memory', icon: <HddOutlined />, label: '记忆' },
  { key: '/graph', icon: <DeploymentUnitOutlined />, label: '知识图谱' },
  { key: '/settings/models', icon: <SettingOutlined />, label: '模型配置' },
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
        width={216}
        style={{
          overflow: 'hidden',
          borderInlineEnd: '1px solid #f0f0f0',
        }}
      >
        <div
          style={{
            height: 60,
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            paddingInline: 20,
            color: '#171719',
          }}
        >
          <div
            style={{
              width: 30,
              height: 30,
              borderRadius: 8,
              background: 'linear-gradient(135deg, #155EEF, #5B8DEF)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 700,
              fontSize: 16,
              color: '#fff',
            }}
          >
            彗
          </div>
          <span style={{ fontWeight: 600, fontSize: 17 }}>彗记 Comet</span>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ borderInlineEnd: 'none', marginTop: 8 }}
        />
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
          <span style={{ color: '#667085', fontSize: 14 }}>
            个人 AI 知识库与记忆助手
          </span>
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
