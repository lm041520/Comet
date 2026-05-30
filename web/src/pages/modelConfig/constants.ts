import type { ModelType, Provider } from '@/api/models'

export const TYPE_OPTIONS: { label: string; value: ModelType }[] = [
  { label: '对话模型', value: 'chat' },
  { label: '多模态模型', value: 'multimodal' },
  { label: 'Embedding 模型', value: 'embedding' },
  { label: 'Rerank 模型', value: 'rerank' },
]

export const TYPE_LABEL: Record<ModelType, string> = {
  chat: '对话',
  multimodal: '多模态',
  embedding: 'Embedding',
  rerank: 'Rerank',
}

export const PROVIDER_OPTIONS: { label: string; value: Provider }[] = [
  { label: 'OpenAI', value: 'openai' },
  { label: '通义千问', value: 'qwen' },
  { label: '豆包', value: 'doubao' },
  { label: 'DeepSeek', value: 'deepseek' },
]

// 各 provider 默认 base_url，与后端 provider.py 保持一致
export const PROVIDER_DEFAULT_BASE_URL: Record<Provider, string> = {
  openai: 'https://api.openai.com/v1',
  qwen: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  doubao: 'https://ark.cn-beijing.volces.com/api/v3',
  deepseek: 'https://api.deepseek.com/v1',
}

export const CAPABILITY_OPTIONS = [
  { label: 'Function Call（工具调用）', value: 'function_call' },
  { label: 'Vision（图片理解）', value: 'vision' },
]
