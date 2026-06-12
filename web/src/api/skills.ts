import client from './client'

interface Wrapped<T> {
  code: number
  message: string
  data: T
}

export interface FewShot {
  input: string
  output: string
}

export interface SkillConfig {
  quick_prompts?: string[]
  few_shots?: FewShot[]
}

export interface Skill {
  id: string
  name: string
  description: string
  icon: string
  prompt: string
  tool_keys: string[]
  kb_id: string | null
  enabled: boolean
  config: SkillConfig
  is_builtin: boolean
}

export interface SkillInput {
  name: string
  description?: string
  icon?: string
  prompt?: string
  tool_keys?: string[]
  kb_id?: string | null
  enabled?: boolean
  config?: SkillConfig
}

export interface BuiltinSkill {
  key: string
  name: string
  description: string
  icon: string
  prompt: string
  tool_keys: string[]
  config: SkillConfig
}

export const skillApi = {
  list() {
    return client.get<unknown, Wrapped<Skill[]>>('/skills')
  },
  builtins() {
    return client.get<unknown, Wrapped<BuiltinSkill[]>>('/skills/builtins')
  },
  create(body: SkillInput) {
    return client.post<unknown, Wrapped<Skill>>('/skills', body)
  },
  addBuiltin(key: string) {
    return client.post<unknown, Wrapped<Skill>>(`/skills/builtins/${key}`, {})
  },
  optimizePrompt(prompt: string) {
    return client.post<unknown, Wrapped<{ optimized: string }>>(
      '/skills/optimize-prompt',
      { prompt },
    )
  },
  update(id: string, body: Partial<SkillInput>) {
    return client.put<unknown, Wrapped<Skill>>(`/skills/${id}`, body)
  },
  remove(id: string) {
    return client.delete<unknown, Wrapped<null>>(`/skills/${id}`)
  },
}
