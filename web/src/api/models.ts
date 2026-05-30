import client from './client'

interface Wrapped<T> {
  code: number
  message: string
  data: T
}

export type ModelType = 'chat' | 'multimodal' | 'embedding'
export type Provider = 'openai' | 'qwen' | 'doubao' | 'deepseek'

export interface ModelConfigItem {
  id: string
  type: ModelType
  provider: Provider
  name: string
  model_name: string
  api_key_masked: string
  base_url: string
  capability: string[]
  is_default: boolean
  created_at: string
}

export interface ModelConfigPayload {
  type: ModelType
  provider: Provider
  name: string
  model_name: string
  api_key: string
  base_url: string
  capability: string[]
  is_default: boolean
}

export const modelApi = {
  list(type?: ModelType) {
    const q = type ? `?type=${type}` : ''
    return client.get<unknown, Wrapped<ModelConfigItem[]>>(`/models${q}`)
  },
  create(payload: ModelConfigPayload) {
    return client.post<unknown, Wrapped<ModelConfigItem>>('/models', payload)
  },
  update(id: string, payload: Partial<ModelConfigPayload>) {
    return client.put<unknown, Wrapped<ModelConfigItem>>(`/models/${id}`, payload)
  },
  remove(id: string) {
    return client.delete<unknown, Wrapped<null>>(`/models/${id}`)
  },
  test(id: string) {
    return client.post<unknown, Wrapped<{ success: boolean; message: string }>>(
      `/models/${id}/test`,
    )
  },
  setDefault(id: string) {
    return client.put<unknown, Wrapped<ModelConfigItem>>(`/models/${id}/default`)
  },
}
