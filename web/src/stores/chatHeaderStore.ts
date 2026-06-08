import { create } from 'zustand'

// 聊天页把「会话历史 / 新对话」两个操作回调注册到这里，
// 供 MainLayout 顶栏在手机端聊天页渲染（替代搜索框），合并成一行。
interface ChatHeaderState {
  active: boolean // 当前是否在聊天页（已注册操作）
  openHistory?: () => void // 打开会话历史抽屉
  newChat?: () => void // 新建对话
  register: (actions: { openHistory: () => void; newChat: () => void }) => void
  clear: () => void
}

export const useChatHeaderStore = create<ChatHeaderState>((set) => ({
  active: false,
  register: ({ openHistory, newChat }) => set({ active: true, openHistory, newChat }),
  clear: () => set({ active: false, openHistory: undefined, newChat: undefined }),
}))
