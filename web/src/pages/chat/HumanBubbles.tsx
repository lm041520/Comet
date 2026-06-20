import { useEffect, useRef, useState } from 'react'
import MarkdownMessage from '@/components/MarkdownMessage'
import { splitBubbles } from './types'

/**
 * 真人模式多气泡：把一条回复按 [[next]] 拆成多个微信式气泡，逐条延时「演」出来，像真人打字。
 *
 * - instant=true（历史消息）：直接全部展开，不重放动画。
 * - 否则（本次新生成）：从「正在输入…」开始，逐条揭示；每条按字数算停顿，模拟真人思考+打字。
 *   动画由「是否本次生成」驱动，而非流式状态——短回复整段瞬间到达时也照样逐条演，不会一次性蹦出。
 * - 节奏只依赖 segLen / shown / instant，不依赖 segs 数组本身，避免流式 token 重置定时器。
 */
export default function HumanBubbles({
  content,
  streaming,
  instant,
}: {
  content: string
  streaming?: boolean
  instant?: boolean
}) {
  const segs = splitBubbles(content)
  const segsRef = useRef(segs)
  segsRef.current = segs
  const segLen = segs.length
  // 历史消息直接全显；新消息从 0 开始（先显示「正在输入…」再逐条冒出来）
  const [shown, setShown] = useState(() => (instant ? segLen : 0))

  useEffect(() => {
    if (instant) {
      setShown(segLen)
      return
    }
    // 流式未结束时，保留最后一条（可能还在生成）不揭示；结束后全部可揭示
    const playable = streaming ? Math.max(0, segLen - 1) : segLen
    if (shown >= playable) return
    const nextText = segsRef.current[shown] || ''
    // 第一条前先「思考」一下；之后每条按字数算打字时间（短句也至少 ~0.9s，长句最多 ~3s）
    const base = shown === 0 ? 900 : 700
    const delay = Math.min(3000, base + nextText.length * 70)
    const t = window.setTimeout(() => setShown((s) => s + 1), delay)
    return () => clearTimeout(t)
  }, [shown, segLen, streaming, instant])

  const visible = segs.slice(0, shown)
  const moreComing = !instant && (shown < segLen || streaming)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-start' }}>
      {visible.map((seg, i) => (
        <div key={i} className="human-bubble">
          <MarkdownMessage content={seg} />
        </div>
      ))}
      {moreComing && (
        <div className="human-bubble human-bubble-typing" aria-label="正在输入">
          <span className="typing-dot" />
          <span className="typing-dot" />
          <span className="typing-dot" />
        </div>
      )}
    </div>
  )
}
