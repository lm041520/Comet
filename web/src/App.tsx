import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import MainLayout from './layouts/MainLayout'
import HomePage from './pages/HomePage'
import LoginPage from './pages/LoginPage'
import ModelConfigPage from './pages/ModelConfigPage'
import KnowledgeBasePage from './pages/KnowledgeBasePage'
import KnowledgeDetailPage from './pages/KnowledgeDetailPage'
import ImagePage from './pages/ImagePage'
import MemoryPage from './pages/MemoryPage'
import GraphPage from './pages/GraphPage'
import MusicLibraryPage from './pages/MusicLibraryPage'
import ChatPage from './pages/ChatPage'
import GroupChatPage from './pages/GroupChatPage'
import AgentConfigPage from './pages/AgentConfigPage'
import SkillPage from './pages/SkillPage'
import ToolConfigPage from './pages/ToolConfigPage'
import SearchPage from './pages/SearchPage'
import FavoritesPage from './pages/FavoritesPage'
import ProfilePage from './pages/ProfilePage'
import SharePage from './pages/SharePage'
import RequireAuth from './components/RequireAuth'

// 阶段1：登录页 + 路由守卫；主布局需登录后访问
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/s/:token" element={<SharePage />} />
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
          <Route path="group-chat" element={<GroupChatPage />} />
          <Route path="knowledge" element={<KnowledgeBasePage />} />
          <Route path="knowledge-bases/:kbId" element={<KnowledgeDetailPage />} />
          <Route path="images" element={<ImagePage />} />
          <Route path="memory" element={<MemoryPage />} />
          <Route path="graph" element={<GraphPage />} />
          <Route path="music" element={<MusicLibraryPage />} />
          <Route path="search" element={<SearchPage />} />
          <Route path="favorites" element={<FavoritesPage />} />
          <Route path="profile" element={<ProfilePage />} />
          <Route path="settings/models" element={<ModelConfigPage />} />
          <Route path="settings/agent" element={<AgentConfigPage />} />
          <Route path="settings/skills" element={<SkillPage />} />
          <Route path="settings/tools" element={<ToolConfigPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
