import { useEffect, useState } from 'react'
import {
  Button,
  Divider,
  Input,
  Modal,
  Select,
  Space,
  Tag,
  message as antdMessage,
} from 'antd'
import { CloseOutlined, PlusOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { skillApi, type Skill, type SkillInput } from '@/api/skills'
import { toolsApi, type ToolItem } from '@/api/tools'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBaseStore'

interface Props {
  open: boolean
  skill: Skill | null // null = 新建
  onClose: () => void
  onSaved: () => void
}

// 常用图标候选（emoji）
const ICONS = ['🧩', '📄', '🔍', '📝', '🌐', '💡', '🧠', '⚙️', '🎯', '📚', '✍️', '🗂️']

export default function SkillEditModal({ open, skill, onClose, onSaved }: Props) {
  const [name, setName] = useState('')
  const [icon, setIcon] = useState('🧩')
  const [description, setDescription] = useState('')
  const [prompt, setPrompt] = useState('')
  const [toolKeys, setToolKeys] = useState<string[]>([])
  const [kbId, setKbId] = useState<string | null>(null)
  const [quickPrompts, setQuickPrompts] = useState<string[]>([])
  const [enabled, setEnabled] = useState(true)
  const [saving, setSaving] = useState(false)
  const [optimizing, setOptimizing] = useState(false)
  const [tools, setTools] = useState<ToolItem[]>([])

  const kbList = useKnowledgeBaseStore((s) => s.list)
  const ensureKbLoaded = useKnowledgeBaseStore((s) => s.ensureLoaded)

  useEffect(() => {
    if (open) {
      setName(skill?.name ?? '')
      setIcon(skill?.icon ?? '🧩')
      setDescription(skill?.description ?? '')
      setPrompt(skill?.prompt ?? '')
      setToolKeys(skill?.tool_keys ?? [])
      setKbId(skill?.kb_id ?? null)
      setQuickPrompts(skill?.config?.quick_prompts ?? [])
      setEnabled(skill?.enabled ?? true)
      ensureKbLoaded()
      // 工具列表（白名单候选）：只取内置工具
      toolsApi
        .list()
        .then(({ data }) => setTools(data.filter((t) => t.tool_type === 'builtin')))
        .catch(() => setTools([]))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, skill])

  const updateQuickPrompt = (idx: number, val: string) => {
    setQuickPrompts((prev) => prev.map((p, i) => (i === idx ? val : p)))
  }
  const addQuickPrompt = () => setQuickPrompts((prev) => [...prev, ''])
  const removeQuickPrompt = (idx: number) =>
    setQuickPrompts((prev) => prev.filter((_, i) => i !== idx))

  const onOptimize = async () => {
    const raw = prompt.trim()
    if (!raw) {
      antdMessage.warning('请先填写任务提示词')
      return
    }
    setOptimizing(true)
    try {
      const { data } = await skillApi.optimizePrompt(raw)
      setPrompt(data.optimized)
      antdMessage.success('已优化，可继续微调')
    } catch (e) {
      antdMessage.error((e as Error).message)
    } finally {
      setOptimizing(false)
    }
  }

  const onSave = async () => {
    if (!name.trim()) {
      antdMessage.warning('请填写技能名')
      return
    }
    const payload: SkillInput = {
      name: name.trim(),
      icon,
      description: description.trim(),
      prompt,
      tool_keys: toolKeys,
      kb_id: kbId ?? '',
      enabled,
      config: {
        quick_prompts: quickPrompts.map((p) => p.trim()).filter(Boolean),
        few_shots: skill?.config?.few_shots ?? [],
      },
    }
    setSaving(true)
    try {
      if (skill) {
        await skillApi.update(skill.id, payload)
        antdMessage.success('已保存')
      } else {
        await skillApi.create(payload)
        antdMessage.success('已创建')
      }
      onSaved()
      onClose()
    } catch (e) {
      antdMessage.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={open}
      onCancel={onClose}
      onOk={onSave}
      confirmLoading={saving}
      okText="保存"
      cancelText="取消"
      title={skill ? '编辑技能' : '新建技能'}
      width={680}
      styles={{ body: { paddingTop: 12, maxHeight: '70vh', overflowY: 'auto' } }}
    >
      <div className="skill-field-label">图标</div>
      <Space wrap size={6}>
        {ICONS.map((ic) => (
          <button
            key={ic}
            type="button"
            className={`skill-icon-pick${icon === ic ? ' active' : ''}`}
            onClick={() => setIcon(ic)}
          >
            {ic}
          </button>
        ))}
      </Space>

      <div className="skill-field-label" style={{ marginTop: 14 }}>
        技能名
      </div>
      <Input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="例如：论文精读 / 代码审查"
        maxLength={64}
      />

      <div className="skill-field-label" style={{ marginTop: 14 }}>
        简介
      </div>
      <Input
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="一句话说明这个技能干什么"
        maxLength={256}
      />

      <div className="skill-field-label" style={{ marginTop: 14 }}>
        <Space>
          <span>任务提示词</span>
          <Button
            size="small"
            type="link"
            icon={<ThunderboltOutlined />}
            loading={optimizing}
            onClick={onOptimize}
            style={{ padding: 0 }}
          >
            优化
          </Button>
        </Space>
      </div>
      <Input.TextArea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        autoSize={{ minRows: 4, maxRows: 12 }}
        placeholder="描述这个技能要完成的专项任务、输出要求、风格等。会与角色卡人设叠加注入。"
        maxLength={8000}
      />

      <Divider style={{ margin: '18px 0 12px' }} />

      <div className="skill-field-label">
        限定工具（白名单）
        <span className="skill-field-tip">勾了就只用这些工具，留空=不限定（用全局配置）</span>
      </div>
      <Select
        mode="multiple"
        value={toolKeys}
        onChange={setToolKeys}
        style={{ width: '100%' }}
        placeholder="留空表示不限定工具"
        allowClear
        options={tools.map((t) => ({
          value: t.tool_key,
          label: `${t.icon} ${t.name}`,
        }))}
      />

      <div className="skill-field-label" style={{ marginTop: 14 }}>
        绑定知识库
        <span className="skill-field-tip">绑了则该技能只检索此库，优先于对话页启用的库</span>
      </div>
      <Select
        value={kbId ?? undefined}
        onChange={(v) => setKbId(v ?? null)}
        style={{ width: '100%' }}
        placeholder="不绑定（用对话页启用的库集合）"
        allowClear
        options={kbList.map((k) => ({
          value: k.id,
          label: `${k.icon ?? '📚'} ${k.name}`,
        }))}
      />

      <div className="skill-field-label" style={{ marginTop: 14 }}>
        快捷开场提问
        <span className="skill-field-tip">挂载技能后对话框上方浮出一键发送按钮</span>
      </div>
      <Space direction="vertical" style={{ width: '100%' }} size={8}>
        {quickPrompts.map((qp, idx) => (
          <Space.Compact key={idx} style={{ width: '100%' }}>
            <Input
              value={qp}
              onChange={(e) => updateQuickPrompt(idx, e.target.value)}
              placeholder="例如：帮我总结这篇论文的核心贡献"
              maxLength={200}
            />
            <Button icon={<CloseOutlined />} onClick={() => removeQuickPrompt(idx)} />
          </Space.Compact>
        ))}
        <Button
          type="dashed"
          icon={<PlusOutlined />}
          onClick={addQuickPrompt}
          block
          disabled={quickPrompts.length >= 8}
        >
          添加快捷提问
        </Button>
      </Space>

      {skill?.is_builtin && (
        <div style={{ marginTop: 14 }}>
          <Tag color="blue">来自内置模板</Tag>
        </div>
      )}
    </Modal>
  )
}
