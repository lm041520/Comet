import client from './client'

interface Wrapped<T> {
  code: number
  message: string
  data: T
}

export type MemoryStatus = 'pending' | 'extracting' | 'done' | 'failed'

export interface MemoryStats {
  dialogue_id: string
  chunks: number
  statements: number
  entities: number
  relations: number
  entity_ids: string[]
}

export interface MemoryItem {
  id: string
  raw_text: string
  source: 'auto' | 'manual'
  status: MemoryStatus
  error_msg: string | null
  graph_stats: MemoryStats | null
  created_at: string
}

export interface MemoryListData {
  total: number
  page: number
  page_size: number
  items: MemoryItem[]
}

export interface MemoryRelation {
  predicate: string
  object_name: string | null
  object_type: string | null
  source_text: string | null
}

export interface MemoryHit {
  id: string
  name: string
  type: string
  description: string | null
  aliases: string[]
  score: number
  relations: MemoryRelation[]
}

// 画像：实体（含一跳关系）
export interface EntityRelation {
  predicate: string
  object_name: string | null
  object_type: string | null
}

export interface ProfileEntity {
  id: string
  name: string
  type: string
  description: string
  aliases: string[]
  relations: EntityRelation[]
  importance: number
  memory_layer: string
  access_count: number
  mention_count: number
  core_facts: string[]
  traits: string[]
}

export interface ProfileGroup {
  type: string
  entities: ProfileEntity[]
}

export interface MemoryProfile {
  total: number
  type_counts: Record<string, number>
  groups: ProfileGroup[]
}

export interface Community {
  id: string
  name: string
  summary: string
  member_count: number
}

export interface CommunityMember {
  id: string
  name: string
  type: string
  description: string
  aliases: string[]
}

// 知识图谱
export interface GraphNode {
  id: string
  name: string
  type: string
  description: string
  community_id: string | null
  importance?: number
  memory_layer?: string
  access_count?: number
  mention_count?: number
  aliases?: string[]
  core_facts?: string[]
  traits?: string[]
}

export interface GraphEdge {
  source: string
  target: string
  predicate: string
  predicate_surface: string
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
  communities: Community[]
}

export interface EntitySubgraph {
  center: string
  nodes: GraphNode[]
  edges: GraphEdge[]
}

// 事件时间线
export interface TimelineParticipant {
  id: string
  name: string
  type: string
}

export interface TimelineEvent {
  id: string
  title: string
  description: string
  event_time: string | null
  created_at: string | null
  participants: TimelineParticipant[]
}

export const memoryApi = {
  remember(text: string) {
    return client.post<unknown, Wrapped<MemoryItem>>('/memories/remember', { text })
  },
  profile() {
    return client.get<unknown, Wrapped<MemoryProfile>>('/memories/profile')
  },
  deleteEntity(entityId: string) {
    return client.delete<unknown, Wrapped<null>>(`/memories/entity/${entityId}`)
  },
  communities() {
    return client.get<unknown, Wrapped<Community[]>>('/memories/communities')
  },
  communityMembers(id: string) {
    return client.get<unknown, Wrapped<CommunityMember[]>>(`/memories/communities/${id}`)
  },
  recluster() {
    return client.post<unknown, Wrapped<null>>('/memories/recluster')
  },
  mergeDuplicates() {
    return client.post<unknown, Wrapped<{ removed: number }>>('/memories/merge-duplicates')
  },
  consolidate() {
    return client.post<
      unknown,
      Wrapped<{ promoted_entities: number; promoted_statements: number; enhanced_profiles: number }>
    >('/memories/consolidate')
  },
  graph() {
    return client.get<unknown, Wrapped<GraphData>>('/memories/graph')
  },
  entitySubgraph(id: string) {
    return client.get<unknown, Wrapped<EntitySubgraph>>(`/memories/graph/entity/${id}`)
  },
  timeline() {
    return client.get<unknown, Wrapped<TimelineEvent[]>>('/memories/timeline')
  },
  list(page = 1, pageSize = 20) {
    const q = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
    return client.get<unknown, Wrapped<MemoryListData>>(`/memories?${q.toString()}`)
  },
  detail(id: string) {
    return client.get<unknown, Wrapped<MemoryItem>>(`/memories/${id}`)
  },
  remove(id: string) {
    return client.delete<unknown, Wrapped<null>>(`/memories/${id}`)
  },
  search(query: string, topK = 10) {
    return client.post<unknown, Wrapped<MemoryHit[]>>('/memories/search', {
      query,
      top_k: topK,
    })
  },
}
