import client from './client'

interface Wrapped<T> {
  code: number
  message: string
  data: T
}

export interface TagItem {
  id: string
  name: string
  color: string
  doc_count: number
}

export const tagApi = {
  list(scope: 'all' | 'document' | 'image' = 'all') {
    return client.get<unknown, Wrapped<TagItem[]>>(`/tags?scope=${scope}`)
  },
  update(id: string, payload: { name?: string; color?: string }) {
    return client.put<unknown, Wrapped<TagItem>>(`/tags/${id}`, payload)
  },
  merge(sourceId: string, targetId: string) {
    return client.post<unknown, Wrapped<null>>('/tags/merge', {
      source_id: sourceId,
      target_id: targetId,
    })
  },
  remove(id: string) {
    return client.delete<unknown, Wrapped<null>>(`/tags/${id}`)
  },
}
