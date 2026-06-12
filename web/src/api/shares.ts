import client from './client'

interface Wrapped<T> {
  code: number
  message: string
  data: T
}

export interface Share {
  id: string
  conversation_id: string
  share_token: string
  title: string
  is_active: boolean
  expire_at: string | null
  view_count: number
  created_at: string | null
}

export interface SharePublicMessage {
  role: string
  content: string
  images?: string[]
  sender_name?: string | null
  sender_avatar?: string | null
}

export interface SharePublic {
  title: string
  messages: SharePublicMessage[]
  user_avatar?: string | null
  ai_avatar?: string | null
  ai_name?: string | null
  created_at: string | null
}

export const shareApi = {
  create(conversationId: string, expireDays?: number | null, title?: string) {
    return client.post<unknown, Wrapped<Share>>(
      `/conversations/${conversationId}/share`,
      { expire_days: expireDays ?? null, title: title ?? null },
    )
  },
  list() {
    return client.get<unknown, Wrapped<Share[]>>('/shares')
  },
  revoke(id: string) {
    return client.delete<unknown, Wrapped<null>>(`/shares/${id}`)
  },
  // 公开查看：无需登录，凭 token 取分享快照
  getPublic(token: string) {
    return client.get<unknown, Wrapped<SharePublic>>(`/public/shares/${token}`)
  },
}
