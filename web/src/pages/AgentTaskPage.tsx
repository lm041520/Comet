import { useCallback, useEffect, useState } from 'react'
import {
  App,
  Button,
  Card,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Select,
  Switch,
  Tag,
  TimePicker,
  Typography,
} from 'antd'
import {
  ClockCircleOutlined,
  DeleteOutlined,
  EditOutlined,
  HighlightOutlined,
  HistoryOutlined,
  PlusOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { useNavigate } from 'react-router-dom'
import {
  agentTaskApi,
  type AgentTask,
  type AgentTaskRun,
  type AgentTaskUpsert,
  type TriggerType,
} from '@/api/agentTask'
import { researchApi } from '@/api/research'

const { TextArea } = Input

const WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

const EXAMPLES = [
  '每天汇总 AI Agent / 大模型开发岗的最新秋招岗位与投递链接',
  '每天追踪大模型行业要闻与重要发布',
  '每周一总结上周 AI Agent 开源项目热点',
]

function triggerText(t: AgentTask): string {
  if (t.trigger_type === 'interval') return `每隔 ${t.trigger_interval_hours} 小时`
  if (t.trigger_type === 'weekly')
    return `每${WEEKDAYS[t.trigger_weekday ?? 0]} ${t.trigger_time}`
  return `每天 ${t.trigger_time}`
}

export default function AgentTaskPage() {
  const { message, modal } = App.useApp()
  const navigate = useNavigate()
  const [tasks, setTasks] = useState<AgentTask[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<AgentTask | null>(null)
  const [polishing, setPolishing] = useState(false)
  const [runsOpen, setRunsOpen] = useState(false)
  const [runsTask, setRunsTask] = useState<AgentTask | null>(null)
  const [runs, setRuns] = useState<AgentTaskRun[]>([])
  const [runsLoading, setRunsLoading] = useState(false)
  const [form] = Form.useForm()
  const triggerType = Form.useWatch('trigger_type', form) as TriggerType | undefined

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await agentTaskApi.list()
      setTasks(res.data)
    } catch {
      /* 忽略 */
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    // 进页即标记简报已读，清菜单红点
    agentTaskApi.markSeen().catch(() => {})
  }, [load])

  const openRuns = async (t: AgentTask) => {
    setRunsTask(t)
    setRunsOpen(true)
    setRunsLoading(true)
    setRuns([])
    try {
      const { data } = await agentTaskApi.runs(t.id)
      setRuns(data)
    } catch (e) {
      message.error((e as { message?: string })?.message || '加载历史失败')
    } finally {
      setRunsLoading(false)
    }
  }

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({
      trigger_type: 'daily',
      trigger_time: dayjs('09:00', 'HH:mm'),
      enabled: true,
      notify_enabled: true,
    })
    setModalOpen(true)
  }

  const openEdit = (t: AgentTask) => {
    setEditing(t)
    form.setFieldsValue({
      name: t.name,
      instruction: t.instruction,
      trigger_type: t.trigger_type,
      trigger_time: t.trigger_time ? dayjs(t.trigger_time, 'HH:mm') : dayjs('09:00', 'HH:mm'),
      trigger_weekday: t.trigger_weekday ?? 0,
      trigger_interval_hours: t.trigger_interval_hours ?? 24,
      enabled: t.enabled,
      notify_enabled: t.notify_enabled,
    })
    setModalOpen(true)
  }

  const submit = async () => {
    const v = await form.validateFields()
    const body: AgentTaskUpsert = {
      name: v.name.trim(),
      instruction: v.instruction.trim(),
      trigger_type: v.trigger_type,
      trigger_time:
        v.trigger_type === 'interval' ? null : dayjs(v.trigger_time).format('HH:mm'),
      trigger_weekday: v.trigger_type === 'weekly' ? v.trigger_weekday : null,
      trigger_interval_hours:
        v.trigger_type === 'interval' ? v.trigger_interval_hours : null,
      enabled: v.enabled,
      notify_enabled: v.notify_enabled,
    }
    try {
      if (editing) {
        await agentTaskApi.update(editing.id, body)
        message.success('已保存')
      } else {
        await agentTaskApi.create(body)
        message.success('已创建')
      }
      setModalOpen(false)
      load()
    } catch (err) {
      message.error((err as { message?: string })?.message || '保存失败')
    }
  }

  const toggle = async (t: AgentTask, enabled: boolean) => {
    try {
      await agentTaskApi.setEnabled(t.id, enabled)
      load()
    } catch {
      message.error('操作失败')
    }
  }

  const runNow = async (t: AgentTask) => {
    try {
      await agentTaskApi.runNow(t.id)
      message.success('已触发运行，稍后在深度研究里查看报告')
    } catch (err) {
      message.error((err as { message?: string })?.message || '触发失败')
    }
  }

  const polish = async () => {
    const raw = (form.getFieldValue('instruction') as string | undefined)?.trim()
    if (!raw) {
      message.warning('请先填写研究指令再润色')
      return
    }
    setPolishing(true)
    try {
      const res = await researchApi.optimizeTopic(raw)
      form.setFieldValue('instruction', res.data.optimized)
      message.success('已润色')
    } catch (err) {
      message.error((err as { message?: string })?.message || '润色失败')
    } finally {
      setPolishing(false)
    }
  }

  const remove = (t: AgentTask) => {
    modal.confirm({
      title: '删除任务',
      content: `确定删除「${t.name}」吗？已生成的报告不受影响。`,
      okType: 'danger',
      onOk: async () => {
        await agentTaskApi.remove(t.id)
        message.success('已删除')
        load()
      },
    })
  }

  return (
    <div className="fluid-page">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>
            <ClockCircleOutlined /> 定时任务
          </Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            到点自动跑深度研究并生成报告，结果在「深度研究」里查看。需配好对话模型 + 联网搜索模型。
          </Typography.Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建任务
        </Button>
      </div>

      {!loading && tasks.length === 0 && (
        <Empty description="还没有定时任务，新建一个让 AI 每天帮你盯着" style={{ marginTop: 60 }}>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建任务
          </Button>
        </Empty>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {tasks.map((t) => (
          <Card key={t.id} styles={{ body: { padding: 16 } }}>
            <div className="agent-task-card-row">
              <div className="agent-task-main">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <span style={{ fontWeight: 600, fontSize: 15 }}>{t.name}</span>
                  <Tag icon={<ClockCircleOutlined />} color="blue">{triggerText(t)}</Tag>
                  {t.last_status === 'running' && <Tag color="processing">运行中</Tag>}
                  {t.last_status === 'done' && <Tag color="success">上次成功</Tag>}
                  {t.last_status === 'failed' && <Tag color="error">上次失败</Tag>}
                </div>
                <Typography.Paragraph
                  type="secondary"
                  style={{ margin: '8px 0 6px', fontSize: 13 }}
                  ellipsis={{ rows: 2 }}
                >
                  {t.instruction}
                </Typography.Paragraph>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {t.enabled
                    ? `下次运行：${t.next_run_at ? dayjs(t.next_run_at).format('MM-DD HH:mm') : '—'}`
                    : '已停用'}
                  {t.last_run_at && ` · 上次：${dayjs(t.last_run_at).format('MM-DD HH:mm')}`}
                </Typography.Text>
              </div>
              <div className="agent-task-actions">
                <Switch
                  size="small"
                  checked={t.enabled}
                  onChange={(c) => toggle(t, c)}
                />
                <Button size="small" icon={<ThunderboltOutlined />} onClick={() => runNow(t)}>
                  立即运行
                </Button>
                <Button size="small" icon={<HistoryOutlined />} onClick={() => openRuns(t)}>
                  历史
                </Button>
                <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(t)} />
                <Button size="small" danger icon={<DeleteOutlined />} onClick={() => remove(t)} />
              </div>
            </div>
          </Card>
        ))}
      </div>

      <div style={{ marginTop: 20, textAlign: 'center' }}>
        <Button type="link" onClick={() => navigate('/research')}>
          去「深度研究」查看生成的报告 →
        </Button>
      </div>

      <Modal
        title={editing ? '编辑任务' : '新建定时任务'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={submit}
        okText="保存"
        cancelText="取消"
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
          <Form.Item name="name" label="任务名" rules={[{ required: true, message: '请输入任务名' }]}>
            <Input placeholder="例如：每日 AI Agent 秋招追踪" maxLength={128} />
          </Form.Item>
          <Form.Item
            name="instruction"
            label={
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                研究指令
                <Button
                  size="small"
                  type="link"
                  icon={<HighlightOutlined />}
                  loading={polishing}
                  onClick={polish}
                  style={{ padding: 0, height: 'auto', fontSize: 12 }}
                >
                  AI 润色
                </Button>
              </span>
            }
            rules={[{ required: true, message: '请输入研究指令' }]}
            extra="到点会把这句话当作研究主题，自动跑一遍深度研究"
          >
            <TextArea rows={3} placeholder="例如：汇总 AI Agent / 大模型开发岗的最新秋招岗位、要求与投递链接" maxLength={2000} />
          </Form.Item>
          <div style={{ marginBottom: 12, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {EXAMPLES.map((ex) => (
              <Tag
                key={ex}
                style={{ cursor: 'pointer' }}
                onClick={() => form.setFieldValue('instruction', ex)}
              >
                {ex}
              </Tag>
            ))}
          </div>
          <Form.Item name="trigger_type" label="触发方式" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'daily', label: '每天' },
                { value: 'weekly', label: '每周' },
                { value: 'interval', label: '每隔 N 小时' },
              ]}
            />
          </Form.Item>
          {triggerType === 'weekly' && (
            <Form.Item name="trigger_weekday" label="星期" rules={[{ required: true }]}>
              <Select options={WEEKDAYS.map((w, i) => ({ value: i, label: w }))} />
            </Form.Item>
          )}
          {triggerType === 'interval' ? (
            <Form.Item name="trigger_interval_hours" label="间隔（小时）" rules={[{ required: true }]}>
              <InputNumber min={1} max={720} style={{ width: '100%' }} />
            </Form.Item>
          ) : (
            <Form.Item name="trigger_time" label="时间" rules={[{ required: true }]}>
              <TimePicker format="HH:mm" style={{ width: '100%' }} minuteStep={5} />
            </Form.Item>
          )}
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item
            name="notify_enabled"
            label="跑完推送到消息渠道"
            valuePropName="checked"
            extra="完成后把报告摘要推到你配置的消息渠道（需先在「消息推送」配置）"
          >
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title={runsTask ? `运行历史 · ${runsTask.name}` : '运行历史'}
        open={runsOpen}
        onClose={() => setRunsOpen(false)}
        width={420}
        extra={
          runsTask && (
            <Button
              type="primary"
              size="small"
              icon={<ThunderboltOutlined />}
              onClick={() => runNow(runsTask)}
            >
              立即运行一次
            </Button>
          )
        }
      >
        <List
          loading={runsLoading}
          locale={{ emptyText: '还没有运行记录，点「立即运行一次」试试' }}
          dataSource={runs}
          renderItem={(r) => (
            <List.Item
              style={{ cursor: r.status === 'done' ? 'pointer' : 'default' }}
              onClick={() => {
                if (r.status === 'done') navigate(`/research?report=${r.id}`)
              }}
            >
              <List.Item.Meta
                title={
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {r.title}
                    </span>
                    {r.status === 'done' && <Tag color="success">完成</Tag>}
                    {r.status === 'failed' && <Tag color="error">失败</Tag>}
                    {!['done', 'failed'].includes(r.status) && <Tag color="processing">运行中</Tag>}
                  </div>
                }
                description={
                  <div style={{ fontSize: 12 }}>
                    <span style={{ color: '#98A2B3' }}>
                      {r.created_at ? dayjs(r.created_at).format('MM-DD HH:mm') : '—'}
                    </span>
                    {r.status === 'failed' && r.error_msg && (
                      <div style={{ color: '#FF5D34', marginTop: 4 }}>{r.error_msg}</div>
                    )}
                    {r.status === 'failed' && runsTask && (
                      <Button
                        type="link"
                        size="small"
                        style={{ padding: 0, marginTop: 2 }}
                        onClick={(e) => {
                          e.stopPropagation()
                          runNow(runsTask)
                        }}
                      >
                        重试
                      </Button>
                    )}
                  </div>
                }
              />
            </List.Item>
          )}
        />
      </Drawer>
    </div>
  )
}
