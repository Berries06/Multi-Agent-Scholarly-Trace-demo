import { useEffect, useRef, useState, type ReactNode } from 'react'
import brandMark from '../assets/multi-agent-mark.png'
import type { AtlasPaper } from '../types'
import { headingLabel, parseKnowledgeCard, sectionText } from './cards'
import { statusText } from './data'

/** 页面头部：一页一件事，标题用宋体，其余无衬线。 */
export function PageHead({
  title,
  summary,
  actions,
}: {
  title: string
  summary: string
  actions?: ReactNode
}) {
  return (
    <header className="page-head">
      <div>
        <h1>{title}</h1>
        <p>{summary}</p>
      </div>
      {actions ? <div className="page-head__actions">{actions}</div> : null}
    </header>
  )
}

export function SectionHead({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="section__head">
      <h2>{title}</h2>
      {hint ? <span>{hint}</span> : null}
    </div>
  )
}

/** 一个 ⓘ 图标，点开才显示补充说明。
 *
 *  页面上不再摆大段说明文字：真需要讲清的地方收进这里，读者想看我再看。 */
export function InfoTip({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const wrapper = useRef<HTMLSpanElement | null>(null)

  useEffect(() => {
    if (!open) return
    const onDocClick = (event: MouseEvent) => {
      if (wrapper.current && !wrapper.current.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <span className="infotip" ref={wrapper}>
      <button
        type="button"
        className="infotip__btn"
        aria-label={label}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        i
      </button>
      {open ? <span className="infotip__body" role="tooltip">{children}</span> : null}
    </span>
  )
}

/** 键位提示：用键帽样式画出来，比写一句"支持快捷键"直观。 */
export function Keycap({ children }: { children: ReactNode }) {
  return <kbd className="keycap">{children}</kbd>
}

/** 轻量提示：动作之后在页面上短暂出现，可带一个撤销按钮。 */
export function Toast({
  text,
  action,
  onDone,
}: {
  text: string
  action?: { label: string; run: () => void }
  onDone: () => void
}) {
  useEffect(() => {
    const timer = setTimeout(onDone, 6000)
    return () => clearTimeout(timer)
  }, [onDone])

  return (
    <div className="toast" role="status">
      <span>{text}</span>
      {action ? (
        <button type="button" onClick={action.run} className="toast__action">{action.label}</button>
      ) : null}
      <button type="button" onClick={onDone} className="toast__close" aria-label="关闭">×</button>
    </div>
  )
}

/** 机器状态标签：只有「系统接受候选 / 需复核 / 已拒绝」三种，不与人工核验混用。 */
export function StatusTag({ status }: { status: string }) {
  const { text, tone } = statusText(status)
  return <span className={`tag ${tone}`}>{text}</span>
}

export function Meta({ items }: { items: Array<string | false | null | undefined> }) {
  const list = items.filter(Boolean) as string[]
  return <div className="list__meta">{list.map((item) => <span key={item}>{item}</span>)}</div>
}

export function Empty({
  title,
  body,
  danger = false,
}: {
  title: string
  body: string
  danger?: boolean
}) {
  return (
    <div className={`empty${danger ? ' panel blocked' : ''}`}>
      <strong>{title}</strong>
      <p>{body}</p>
    </div>
  )
}

/** 证据原文：头实体与尾实体分别高亮，右侧给出定位信息；定位不到时说清楚，不伪造。 */
export function EvidenceBlock({
  text,
  head,
  tail,
  paperId,
  section,
  start,
  end,
  located,
}: {
  text: string
  head?: string
  tail?: string
  paperId: string
  section: string
  start: number
  end: number
  located: boolean
}) {
  const spans: ReactNode[] = []
  let rest = text
  let key = 0
  const marks: Array<{ index: number; length: number; kind: 'head' | 'tail' }> = []
  for (const [kind, name] of [['head', head], ['tail', tail]] as const) {
    if (!name) continue
    const index = rest.toLowerCase().indexOf(name.toLowerCase())
    if (index >= 0) marks.push({ index, length: name.length, kind })
  }
  marks.sort((left, right) => left.index - right.index)
  let cursor = 0
  for (const mark of marks) {
    if (mark.index < cursor) continue
    if (mark.index > cursor) {
      spans.push(<span key={key++}>{rest.slice(cursor, mark.index)}</span>)
    }
    spans.push(
      <mark key={key++} className={mark.kind === 'tail' ? 'tail' : undefined}>
        {rest.slice(mark.index, mark.index + mark.length)}
      </mark>,
    )
    cursor = mark.index + mark.length
  }
  if (cursor < rest.length) spans.push(<span key={key++}>{rest.slice(cursor)}</span>)

  return (
    <div className="evidence">
      {located ? spans : (
        <p className="note">来源定位失败：按记录的位置取不回原文，这里不显示高亮。</p>
      )}
      <div className="evidence__meta">
        <span>{paperId}</span>
        <span>{section}</span>
        <span>
          {start}–{end}
        </span>
        <span>{located ? '已定位到原文' : '未定位'}</span>
      </div>
    </div>
  )
}

/**
 * 知识卡：版式照用户给的参考图——深绿整面、圆形徽标、金色胶囊、大标题、
 * 2×2 内块、脚注说明、底部白色胶囊。
 *
 * 卡上的每一个字都有来源：标题/作者/年份/出处来自 `/api/atlas` 的 `papers`，
 * 2×2 内块的标签与内容来自 `cards[paper_id]` 的 markdown 原文（只做结构切分），
 * 脚注是该卡片自带的出处说明。没有知识卡就渲染空状态，不拿别的字段拼一张卡。
 */
export function KnowledgeCard({
  paper,
  cardMarkdown,
  domainName,
  paperId,
  onOpenSource,
}: {
  paper: AtlasPaper
  cardMarkdown?: string
  domainName: string
  paperId: string
  onOpenSource?: () => void
}) {
  const parsed = parseKnowledgeCard(cardMarkdown ?? '')
  const cells = parsed.sections.slice(0, 4)
  const tierText = paper.evidence_tier === 'evidence_card' ? '本地有开放全文' : '仅题录'

  const authorLine = paper.authors.length
    ? paper.authors.slice(0, 3).join('、') + (paper.authors.length > 3 ? ' 等' : '')
    : '作者未记录'
  const metaLine = [authorLine, paper.venue || '来源未记录', paper.year ? String(paper.year) : '年份未记录'].join(' · ')

  return (
    <article className="kcard">
      <div className="kcard__top">
        <div className="kcard__brand">
          <span className="kcard__mark">
            <img src={brandMark} alt="" />
          </span>
          <span className="kcard__name">
            研海寻踪
            <small>{domainName || '文献库'}</small>
          </span>
        </div>
        <span className="kcard__tag">知识卡</span>
      </div>

      <h2 className="kcard__title">{paper.title}</h2>
      <p className="kcard__sub">{metaLine}</p>

      {cells.length > 0 ? (
        <dl className="kcard__grid">
          {cells.map((section) => {
            const text = sectionText(section)
            return (
              <div className="kcard__cell" key={section.heading}>
                <dt>{headingLabel(section.heading)}</dt>
                <dd className={text.length > 28 ? 'is-text' : undefined}>{text}</dd>
              </div>
            )
          })}
        </dl>
      ) : (
        <p className="kcard__note">
          这张卡片只有标题与题录：`cards` 里这一篇没有可切分的小标题正文，因此不显示 2×2 内块。
        </p>
      )}

      {parsed.provenance ? <p className="kcard__note">{parsed.provenance}</p> : null}

      <div className="kcard__foot">
        {paper.source_url ? (
          <a className="kcard__btn" href={paper.source_url} target="_blank" rel="noreferrer">
            查看原文出处 →
          </a>
        ) : (
          <button type="button" className="kcard__btn" onClick={onOpenSource}>
            证据档位：{tierText}
          </button>
        )}
        <span className="kcard__meta">
          {tierText} · {paperId}
        </span>
      </div>
    </article>
  )
}

/** 出处块：每个数字都要说明来自哪个库、什么时候、统计口径。 */
export function ProvenanceNote({ lines }: { lines: string[] }) {
  return (
    <div className="panel">
      <div className="panel__body">
        <ul className="checklist">
          {lines.map((line) => (
            <li key={line}>
              <i>·</i>
              <span className="note">{line}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
