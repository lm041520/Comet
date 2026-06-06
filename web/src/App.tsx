import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import MainLayout from './layouts/MainLayout'
import HomePage from './pages/HomePage'
import LoginPage from './pages/LoginPage'
import ModelConfigPage from './pages/ModelConfigPage'
import KnowledgePage from './pages/KnowledgePage'
import ImagePage from './pages/ImagePage'
import MemoryPage from './pages/MemoryPage'
import GraphPage from './pages/GraphPage'
import ChatPage from './pages/ChatPage'
import AgentConfigPage from './pages/AgentConfigPage'
import ToolConfigPage from './pages/ToolConfigPage'
import SearchPage from './pages/SearchPage'
import FavoritesPage from './pages/FavoritesPage'
import RequireAuth from './components/RequireAuth'

// 阶段1：登录页 + 路由守卫；主布局需登录后访问
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <MainLayout />
            </RequireAuth>
          }
        >
          <Route index element={<HomePage />} />
          <Route path="chat" element={<ChatPage />} />
          <Route path="knowledge" element={<KnowledgePage />} />
          <Route path="images" element={<ImagePage />} />
          <Route path="memory" element={<MemoryPage />} />
          <Route path="graph" element={<GraphPage />} />
          <Route path="search" element={<SearchPage />} />
          <Route path="favorites" element={<FavoritesPage />} />
          <Route path="settings/models" element={<ModelConfigPage />} />
          <Route path="settings/agent" element={<AgentConfigPage />} />
          <Route path="settings/tools" element={<ToolConfigPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
