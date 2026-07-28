import client from './client'

interface Wrapped<T> {
  code: number
  message: string
  data: T
}

export type DocStatus = 'pending' | 'parsing' | 'done' | 'failed'

export interface DocTag {
  name: string
  color: string
}

export interface DocumentItem {
  id: string
  kb_id: string | null
  file_name: string
  file_ext: string
  file_size: number
  source_type: string
  source_url: string | null
  status: DocStatus
  progress: number
  chunk_num: number
  error_msg: string | null
  parser_name: string | null
  parser_version: string | null
  parse_status: string | null
  parse_summary: Record<string, unknown>
  parsed_at: string | null
  tags: DocTag[]
  created_at: string
}

export interface DocumentListData {
  total: number
  page: number
  page_size: number
  items: DocumentItem[]
}

export interface SearchHit {
  chunk_id: string
  content: string
  doc_name: string | null
  source_id: string | null
  source_type: string | null
  score: number
  matched_content: string | null
  kb_id: string | null
  block_ids: string[]
  block_types: string[]
  page_start: number | null
  page_end: number | null
  heading_path: string[]
  parser_name: string | null
}

export interface RetrievalScores {
  vector_score: number | null
  vector_es_score: number | null
  vector_normalized: number | null
  bm25_score: number | null
  bm25_normalized: number | null
  fusion_score: number | null
  rerank_score: number | null
}

export interface RetrievalStageRanks {
  vector_rank: number | null
  bm25_rank: number | null
  fusion_rank: number | null
  final_rank: number
}

export interface RetrievalBlock {
  block_id: string
  block_order: number
  block_type: string
  content: string
  page_start: number | null
  page_end: number | null
  heading_path: string[]
  extra_json: Record<string, unknown>
}

export interface RetrievalValidationHit {
  rank: number
  chunk_id: string
  parent_id: string | null
  child_content: string
  parent_content: string
  doc_name: string | null
  source_id: string | null
  kb_id: string | null
  score: number
  scores: RetrievalScores
  stage_ranks: RetrievalStageRanks
  block_ids: string[]
  block_types: string[]
  page_start: number | null
  page_end: number | null
  heading_path: string[]
  chunk_index: number
  parser_name: string | null
  parser_version: string | null
  parse_status: string | null
  warnings: string[]
  blocks: RetrievalBlock[]
}

export interface RetrievalValidationData {
  query: string
  kb_id: string
  top_k: number
  recall_size: number
  vector_weight: number
  bm25_weight: number
  rerank_used: boolean
  rerank_error: string | null
  results: RetrievalValidationHit[]
}

export interface DocumentPreview {
  id: string
  file_name: string
  file_ext: string
  preview_type: 'text' | 'pdf'
  preview_url: string | null
  download_url: string | null
  expires_in: number | null
  is_markdown: boolean
  source_url: string | null
  content: string
  truncated: boolean
}

export const documentApi = {
  list(page = 1, pageSize = 100, tag?: string, kbId?: string) {
    const q = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
    if (tag) q.set('tag', tag)
    if (kbId) q.set('kb_id', kbId)
    return client.get<unknown, Wrapped<DocumentListData>>(`/documents?${q.toString()}`)
  },
  // 上传文档（multipart）
  upload(file: File, kbId?: string) {
    const form = new FormData()
    form.append('file', file)
    if (kbId) form.append('kb_id', kbId)
    return client.post<unknown, Wrapped<DocumentItem>>(
      '/documents/upload',
      form,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    )
  },
  importUrl(url: string, kbId?: string) {
    return client.post<unknown, Wrapped<DocumentItem>>('/documents/from-url', {
      url,
      kb_id: kbId,
    })
  },
  detail(id: string) {
    return client.get<unknown, Wrapped<DocumentItem>>(`/documents/${id}`)
  },
  preview(id: string) {
    return client.get<unknown, Wrapped<DocumentPreview>>(`/documents/${id}/preview`)
  },
  status(id: string) {
    return client.get<unknown, Wrapped<{ status: DocStatus; progress: number; error_msg: string | null }>>(
      `/documents/${id}/status`,
    )
  },
  retry(id: string, parser: 'auto' | 'plain' | 'pymupdf' | 'docling' = 'auto') {
    const q = new URLSearchParams({ parser })
    return client.post<unknown, Wrapped<DocumentItem>>(
      `/documents/${id}/retry?${q.toString()}`,
    )
  },
  remove(id: string) {
    return client.delete<unknown, Wrapped<null>>(`/documents/${id}`)
  },
  move(id: string, kbId: string) {
    return client.put<unknown, Wrapped<DocumentItem>>(`/documents/${id}/move`, {
      kb_id: kbId,
    })
  },
  search(query: string, topK = 5, tags?: string[], kbId?: string) {
    return client.post<unknown, Wrapped<SearchHit[]>>('/documents/search', {
      query,
      top_k: topK,
      tags,
      kb_id: kbId,
    })
  },
  validateRetrieval(query: string, kbId: string, topK = 8) {
    return client.post<unknown, Wrapped<RetrievalValidationData>>(
      '/documents/retrieval-validation',
      { query, kb_id: kbId, top_k: topK },
    )
  },
}
