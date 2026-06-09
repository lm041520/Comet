import client from './client'

interface Wrapped<T> {
  code: number
  message: string
  data: T
}

export type ImageStatus = 'pending' | 'processing' | 'done' | 'failed'

export interface ImageItem {
  id: string
  file_name: string
  file_ext: string
  file_size: number
  url: string
  description: string | null
  objects: string[] | null
  scene: string | null
  tags: { name: string; color: string }[]
  status: ImageStatus
  error_msg: string | null
  created_at: string
}

export interface ImageListData {
  total: number
  page: number
  page_size: number
  items: ImageItem[]
}

export interface ImageSearchHit {
  chunk_id: string
  content: string
  doc_name: string | null
  source_id: string | null
  source_type: string | null
  score: number
}

export const imageApi = {
  list(page = 1, pageSize = 60, tag?: string) {
    const q = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
    if (tag) q.set('tag', tag)
    return client.get<unknown, Wrapped<ImageListData>>(`/images?${q.toString()}`)
  },
  upload(file: File) {
    const form = new FormData()
    form.append('file', file)
    return client.post<unknown, Wrapped<ImageItem>>('/images/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  detail(id: string) {
    return client.get<unknown, Wrapped<ImageItem>>(`/images/${id}`)
  },
  search(query: string, topK = 12) {
    return client.post<unknown, Wrapped<ImageSearchHit[]>>('/images/search', {
      query,
      top_k: topK,
    })
  },
  remove(id: string) {
    return client.delete<unknown, Wrapped<null>>(`/images/${id}`)
  },
}
