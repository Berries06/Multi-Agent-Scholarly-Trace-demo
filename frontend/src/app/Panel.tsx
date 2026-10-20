import { useCallback, useEffect, useRef, useState } from 'react'
import { commitPanel, streamPanel } from '../api'
import type { PanelMessage, PanelResult } from '../types'
import { SectionHead } from './ui'

/** 「AI 组会」：把提出者—批判者—裁判的判定过程做成一段群聊。
 *
 *  设计上的三条硬规矩：
 *  1. 每条发言只讲一件事，长内容收进「看证据」；
 *  2. 判定层是规则代码时，界面上必须写「规则裁判」，不能装作模型在讨论；
 *  3. 采纳是**一键动作**，不是让用户再判一遍；人工复核是抽查与异议，不是必经流程。
 */

const AGENT_STYLE: Record<string, { className: string; label: string }> = {
  提出者: { className: 'panel-msg--proposer', label: '提出者' },
  批判者: { className: 'panel-msg--critic', label: '批判者' },
  裁判: { className: 'panel-msg--judge', label: '裁判' },
  组会: { className: 'panel-msg--chair', label: '组会' },
}

const STATUS_CHIP: Record<string, string> = {
  accepted: '采纳',
  needs_review: '转人工',
  rejected: '驳回',
}

type Scope = 'needs_review' | 'undecided' | 'all'

export function PanelSection({ projectId, onChanged }: { projectId: string; onChanged: () => void }) {
  const [messages, setMessages] = useState<PanelMessage[]>([])
  const [result, setResult] = useState<PanelResult | null>(null)
  const [scope, setScope] = useState<Scope>('needs_review')
  const [limit, setLimit] = useState(20)
  const [running, setRunning] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const streamRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    setMessages([])
    setResult(null)
    setNotice(null)
    setError(null)
  }, [projectId])

  useEffect(() => {
    if (!streamRef.current) return
    streamRef.current.scrollTop = streamRef.current.scrollHeight
  }, [messages])

  const open = useCallback(async () => {
    if (!projectId) return
    setRunning(true)
    setError(null)
    setNotice(null)
    setMessages([])
    setResult(null)
    try {
      const payload = await streamPanel(
        projectId,
        { limit, only: scope },
        {
          onMessage: (message) => setMessages((current) => [...current, message]),
        },
      )
      setResult(payload)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setRunning(false)
    }
  }, [projectId, limit, scope])

  const adopt = async () => {
    if (!result) return
    const accepted = result.verdicts.filter((item) => item.status === 'accepted')
    if (accepted.length === 0) {
      setNotice('这次没有「采纳」的结论，不用写进图谱。')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const outcome = await commitPanel(projectId, {
        decisions: accepted.map((item) => ({
          relation_id: item.relation_id,
          decision: 'include',
          mode_label: result.mode_label,
        })),
      })
      setNotice(`已把 ${outcome.written} 条写进你的图谱，每条的备注里记着“AI 组会采纳”。`)
      onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const acceptedCount = result?.verdicts.filter((item) => item.status === 'accepted').length ?? 0
  const reviewCount = result?.verdicts.filter((item) => item.status === 'needs_review').length ?? 0

  return (
    <div className="section" style={{ marginBottom: 24 }}>
      <SectionHead title="AI 组会" hint="提出者、批判者、裁判各说一句，机器给出结论" />
      <div className="panel">
        <div className="panel__body" style={{ paddingBottom: 8 }}>
          <div className="toolbar" style={{ marginBottom: 10 }}>
            <label className="field">
              <span>这次看哪些</span>
              <select value={scope} onChange={(event) => setScope(event.target.value as Scope)}>
                <option value="needs_review">机器判不了的（待复核）</option>
                <option value="undecided">还没做决定的</option>
                <option value="all">全部候选</option>
              </select>
            </label>
            <label className="field">
              <span>一次几条</span>
              <select value={limit} onChange={(event) => setLimit(Number(event.target.value))}>
                {[10, 20, 30, 50].map((value) => (
                  <option key={value} value={value}>{value} 条</option>
                ))}
              </select>
            </label>
            <button type="button" className="btn btn--primary" onClick={() => void open()} disabled={running || !projectId}>
              {running ? '开会中…' : '让 AI 开会'}
            </button>
            {result ? (
              <button
                type="button"
                className="btn btn--quiet btn--sm"
                onClick={() => void adopt()}
                disabled={busy || acceptedCount === 0}
              >
                {busy ? '写入中…' : `采纳这 ${acceptedCount} 条`}
              </button>
            ) : null}
          </div>

          {error ? <p className="note" style={{ color: 'var(--danger)' }}>{error}</p> : null}
          {notice ? <p className="note">{notice}</p> : null}

          {messages.length === 0 && !running ? (
            <p className="note" style={{ margin: 0 }}>点「让 AI 开会」，三个智能体会逐条过一遍候选关系。</p>
          ) : (
            <div className="panel-chat" ref={streamRef}>
              {result ? (
                <p className="panel-chat__mode">{result.mode_label} · 结论按课题里记的机器状态给</p>
              ) : null}
              {messages.map((message) => {
                const style = AGENT_STYLE[message.agent] ?? AGENT_STYLE.组会
                const isJudge = message.agent === '裁判'
                return (
                  <div key={message.seq} className={`panel-msg ${style.className}`}>
                    <span className="panel-msg__who">{style.label}</span>
                    <div className="panel-msg__bubble">
                      <span className="panel-msg__text">{message.text}</span>
                      {isJudge && message.status ? (
                        <span className={`panel-msg__chip panel-msg__chip--${message.status}`}>
                          {STATUS_CHIP[message.status] ?? message.status}
                          {message.score ? ` · 分 ${Number(message.confidence || 0).toFixed(2)}` : ''}
                        </span>
                      ) : null}
                      {message.evidence_text ? (
                        <>
                          <button
                            type="button"
                            className="panel-msg__toggle"
                            onClick={() => setExpanded(expanded === String(message.seq) ? null : String(message.seq))}
                          >
                            {expanded === String(message.seq) ? '收起证据' : '看证据'}
                          </button>
                          {expanded === String(message.seq) ? (
                            <p className="panel-msg__evidence">
                              {message.evidence_text}
                              <span className="mono"> · {message.paper_id} {message.section_id}</span>
                            </p>
                          ) : null}
                        </>
                      ) : null}
                      {message.checks.length > 1 && message.agent === '批判者' ? (
                        <>
                          <button
                            type="button"
                            className="panel-msg__toggle"
                            onClick={() => setExpanded(expanded === `checks-${message.seq}` ? null : `checks-${message.seq}`)}
                          >
                            {expanded === `checks-${message.seq}` ? '收起检查项' : `看全部 ${message.checks.length} 条检查`}
                          </button>
                          {expanded === `checks-${message.seq}` ? (
                            <ul className="panel-msg__checks">
                              {message.checks.map((check, index) => (
                                <li key={index}>{check}</li>
                              ))}
                            </ul>
                          ) : null}
                        </>
                      ) : null}
                    </div>
                  </div>
                )
              })}
              {running ? <p className="panel-chat__typing">正在核对证据…</p> : null}
            </div>
          )}

          {result ? (
            <div className="toolbar" style={{ marginTop: 10, marginBottom: 0 }}>
              <span className="note" style={{ marginRight: 6 }}>
                过完 {result.counts.processed} 条：采纳 {result.counts.accepted}、转人工 {reviewCount}、驳回 {result.counts.rejected}
                {result.counts.remaining > 0 ? `，还剩 ${result.counts.remaining} 条` : ''}
              </span>
              {result.counts.remaining > 0 ? (
                <button type="button" className="btn btn--quiet btn--sm" onClick={() => void open()} disabled={running}>
                  再来一轮
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
