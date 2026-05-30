import { useEffect, useState } from 'react'
import { Space, Tag } from 'antd'
import { tagApi, type TagItem } from '@/api/tags'

interface Props {
  active?: string
  scope?: 'all' | 'document' | 'image'
  onChange: (tagName?: string) => void
}

/** 标签筛选条：点击某标签筛选，再点取消。单选。 */
export default function TagFilterBar({ active, scope = 'all', onChange }: Props) {
  const [tags, setTags] = useState<TagItem[]>([])

  useEffect(() => {
    tagApi
      .list(scope)
      .then(({ data }) => setTags(data))
      .catch(() => setTags([]))
  }, [scope])

  if (!tags.length) return null

  return (
    <Space wrap style={{ marginBottom: 16 }}>
      <Tag.CheckableTag checked={!active} onChange={() => onChange(undefined)}>
        全部
      </Tag.CheckableTag>
      {tags.map((t) => (
        <Tag.CheckableTag
          key={t.id}
          checked={active === t.name}
          onChange={(checked) => onChange(checked ? t.name : undefined)}
          style={
            active === t.name
              ? { background: t.color, color: '#fff' }
              : { border: `1px solid ${t.color}`, color: t.color }
          }
        >
          {t.name} ({t.doc_count})
        </Tag.CheckableTag>
      ))}
    </Space>
  )
}
