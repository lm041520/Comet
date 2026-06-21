import { useState, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Tooltip, message as antdMessage } from 'antd'
import { CheckOutlined, CopyOutlined } from '@ant-design/icons'
import { copyText } from '@/utils/clipboard'

// 从 React children 里递归抽出纯文本（供复制代码用）
function extractText(node: ReactNode): string {
  if (node == null || node === false || node === true) return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(extractText).join('')
  if (typeof node === 'object' && 'props' in (node as never)) {
    return extractText((node as { props: { children?: ReactNode } }).props.children)
  }
  return ''
}

// 代码块：深色底 + 右上角复制按钮
function CodeBlock({ className, children }: { className?: string; children: ReactNode }) {
  const [copied, setCopied] = useState(false)
  const code = extractText(children).replace(/\n$/, '')
  // 语言名（去掉 language- 前缀）
  const lang = (className || '').replace('language-', '').trim()

  const onCopy = async () => {
    const ok = await copyText(code)
    if (ok) {
      setCopied(true)
      antdMessage.success('已复制代码')
      setTimeout(() => setCopied(false), 1500)
    } else {
      antdMessage.error('复制失败')
    }
  }

  return (
    <div style={{ position: 'relative', margin: '10px 0' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: '#2D2D2D',
          color: '#9CA3AF',
          padding: '6px 12px',
          borderTopLeftRadius: 8,
          borderTopRightRadius: 8,
          fontSize: 12,
        }}
      >
        <span>{lang || 'code'}</span>
        <span
          onClick={onCopy}
          style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4, userSelect: 'none' }}
        >
          {copied ? <CheckOutlined /> : <CopyOutlined />}
          {copied ? '已复制' : '复制'}
        </span>
      </div>
      <pre
        style={{
          background: '#1E1E1E',
          color: '#E6E6E6',
          padding: 14,
          margin: 0,
          borderBottomLeftRadius: 8,
          borderBottomRightRadius: 8,
          overflowX: 'auto',
          fontSize: 13,
          lineHeight: 1.6,
        }}
      >
        <code className={className}>{children}</code>
      </pre>
    </div>
  )
}

// AI 消息的 Markdown 渲染：行内代码浅灰、代码块带复制、表格边框、链接新窗口
export default function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ title, ...props }) => {
            const link = (
              <a {...props} title={title} target="_blank" rel="noreferrer" />
            )
            // 带说明（如研究报告来源角标）时，悬停显示简洁 Tooltip 预知跳转目标
            return title ? (
              <Tooltip title={title} placement="top">
                {link}
              </Tooltip>
            ) : (
              link
            )
          },
          code({ className, children, ...props }) {
            const isInline = !className
            if (isInline) {
              return (
                <code
                  style={{
                    background: '#F2F4F7',
                    padding: '1px 5px',
                    borderRadius: 4,
                    fontSize: 13,
                  }}
                  {...props}
                >
                  {children}
                </code>
              )
            }
            return <CodeBlock className={className}>{children}</CodeBlock>
          },
          // react-markdown 默认会把代码块包一层 pre，这里用 CodeBlock 自带 pre，故 pre 直接透传
          pre: (props) => <>{props.children}</>,
          // 表格包一层可横向滚动容器：列多/内容长时（尤其手机端）横向滑动查看，
          // 避免被窄屏压成「每个字一行」。
          table: (props) => (
            <div className="md-table-wrap">
              <table {...props} />
            </div>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
