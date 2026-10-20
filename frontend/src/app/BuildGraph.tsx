import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  clearRelationDecision,
  decideRelation,
  getEvidenceContext,
  getProjectGraph,
  getProjectRelations,
  getRelationEvidence,
} from '../api'
import type {
  ProjectEvidenceRef,
  ProjectGraph,
  ProjectRelation,
  RelationDecision,
} from '../types'
import type { EvidenceContextPayload } from '../api'
import { PanelSection } from './Panel'
import { useProject } from './project'
import { Empty, InfoTip, Keycap, Meta, PageHead, SectionHead, StatusTag, Toast } from './ui'

const DECISION_LABEL: Record<RelationDecision, string> = {
  include: '已加入我的图谱',
  defer: '暂缓',
  exclude: '排除',
}

const DECISION_TONE: Record<RelationDecision, string> = {
  include: 'tag--accepted',
  defer: 'tag--review',
  exclude: 'tag--rejected',
}

type Filter = 'all' | 'undecided' | RelationDecision

function InlineNotice() {
  const { active } = useProject()
  if (active) return null
  return (
    <Empty
      title="还没有选中的课题"
      body="先去「设置」新建一个课题，再回来构建图谱。"
    />
  )
}

/** 证据片段：标出这条关系引用的原文。片段是引用，不是整篇正文。 */
function EvidenceList({ spans }: { spans: ProjectEvidenceRef[] }) {
  if (spans.length === 0) {
    return (
      <Empty
        title="这条关系没有证据片段"
        body="没有片段就无法核对，这条关系不该当作已被支持。"
      />
    )
  }
  return (
    <div className="evi-stack">
      {spans.map((span) => (
        <figure className="evi" key={span.evidence_id}>
          <blockquote>{span.text || '（这条证据只存了位置，没有存片段正文）'}</blockquote>
          <figcaption className="evidence__meta">
            <span>{span.paper_id}</span>
            <span>{span.section_id || '未标段落'}</span>
            <span>{span.char_start}–{span.char_end}</span>
          </figcaption>
        </figure>
      ))}
    </div>
  )
}

/** 构建图谱：候选队列 / 原文 / 入图决定 三栏。 */
export function BuildGraphPage() {
  const { active } = useProject()
  const [relations, setRelations] = useState<ProjectRelation[]>([])
  const [filter, setFilter] = useState<Filter>('undecided')
  const [keyword, setKeyword] = useState('')
  const [machine, setMachine] = useState('all')
  const [selectedId, setSelectedId] = useState('')
  const [toast, setToast] = useState<{ text: string; relationId: string } | null>(null)
  const [spans, setSpans] = useState<ProjectEvidenceRef[]>([])
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const projectId = active?.project_id ?? ''

  const load = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    try {
      const result = await getProjectRelations(projectId)
      setRelations(result.relations ?? [])
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    void load()
  }, [load])

  const counts = useMemo(() => {
    const tally = { all: relations.length, undecided: 0, include: 0, defer: 0, exclude: 0 }
    for (const relation of relations) {
      if (relation.decision) tally[relation.decision] += 1
      else tally.undecided += 1
    }
    return tally
  }, [relations])

  const visible = useMemo(() => {
    const needle = keyword.trim().toLowerCase()
    const byDecision =
      filter === 'all'
        ? relations
        : filter === 'undecided'
          ? relations.filter((item) => !item.decision)
          : relations.filter((item) => item.decision === filter)
    return byDecision.filter((item) => {
      if (machine !== 'all' && item.machine_status !== machine) return false
      if (!needle) return true
      return `${item.source_name} ${item.target_name} ${item.relation_type} ${item.paper_id}`
        .toLowerCase()
        .includes(needle)
    })
  }, [relations, filter, keyword, machine])

  // 整库接入之后候选可能上千条，列表只渲染前若干条，靠搜索与筛选收窄
  const RENDER_CAP = 200
  const shown = visible.slice(0, RENDER_CAP)

  // 全部审完之后「待决定」是空的，别让页面停在空白队列上；只自动跳一次，之后听用户的。
  const autoJumped = useRef(false)
  useEffect(() => {
    if (autoJumped.current) return
    if (relations.length > 0 && counts.undecided === 0) {
      autoJumped.current = true
      setFilter('all')
    }
  }, [relations.length, counts.undecided])

  const current = visible.find((item) => item.relation_id === selectedId) ?? visible[0]

  useEffect(() => {
    if (!projectId || !current) {
      setSpans([])
      return
    }
    let alive = true
    getRelationEvidence(projectId, current.relation_id)
      .then((result) => { if (alive) setSpans(result.evidence ?? []) })
      .catch(() => { if (alive) setSpans([]) })
    return () => { alive = false }
  }, [projectId, current])

  const decide = async (decision: RelationDecision) => {
    if (!projectId || !current) return
    const target = current
    setBusy(true)
    setError(null)
    try {
      await decideRelation(projectId, target.relation_id, decision, note)
      setNote('')
      setToast({
        text: `${target.source_name} → ${target.target_name}：${DECISION_LABEL[decision]}`,
        relationId: target.relation_id,
      })
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  // 快捷键：J/K 或方向键上下移动，A 加入、S 暂缓、X 排除。
  // 不设依赖数组，每次渲染都换一份最新的闭包，省得读到过期的 visible。
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const tag = (event.target as HTMLElement | null)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (!projectId || !current || visible.length === 0) return
      const key = event.key.toLowerCase()
      const index = visible.findIndex((item) => item.relation_id === current.relation_id)
      if (key === 'j' || event.key === 'ArrowDown') {
        event.preventDefault()
        setSelectedId(visible[Math.min(visible.length - 1, index + 1)].relation_id)
      } else if (key === 'k' || event.key === 'ArrowUp') {
        event.preventDefault()
        setSelectedId(visible[Math.max(0, index - 1)].relation_id)
      } else if (key === 'a') {
        void decide('include')
      } else if (key === 's') {
        void decide('defer')
      } else if (key === 'x') {
        void decide('exclude')
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  if (!active) {
    return (
      <>
        <PageHead title="构建图谱" summary="逐条读原文，再决定这条关系要不要进你的图谱。" />
        <InlineNotice />
      </>
    )
  }

  const undo = async (relationId: string) => {
    if (!projectId) return
    setBusy(true)
    try {
      await clearRelationDecision(projectId, relationId)
      setToast(null)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHead
        title="构建图谱"
        summary="三个智能体先判一轮，你只处理分歧。"
      />

      {error ? <Empty title="操作失败" body={error} danger /> : null}

      <PanelSection
        projectId={projectId}
        onChanged={() => {
          void load()
        }}
      />

      <div className="toolbar">
        {([
          ['undecided', `待决定 ${counts.undecided}`],
          ['include', `已加入 ${counts.include}`],
          ['defer', `暂缓 ${counts.defer}`],
          ['exclude', `排除 ${counts.exclude}`],
          ['all', `全部 ${counts.all}`],
        ] as Array<[Filter, string]>).map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={filter === key ? 'btn btn--primary btn--sm' : 'btn btn--quiet btn--sm'}
            onClick={() => { setFilter(key); setSelectedId('') }}
            aria-pressed={filter === key}
          >
            {label}
          </button>
        ))}
        <span className="note">{loading ? '读取中…' : `共 ${relations.length} 条候选`}</span>
      </div>

      <div className="toolbar">
        <label className="field">
          <span>机器状态</span>
          <select value={machine} onChange={(event) => { setMachine(event.target.value); setSelectedId('') }}>
            <option value="all">全部</option>
            <option value="accepted">系统接受候选</option>
            <option value="needs_review">需复核</option>
            <option value="rejected">已拒绝</option>
          </select>
        </label>
        <label className="field field--grow">
          <span>搜索实体 / 关系类型 / 论文</span>
          <input
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            placeholder="例如：Materials Project，或 BENCHMARKS"
          />
        </label>
        <span className="note">
          命中 {visible.length} 条
          {visible.length > shown.length ? `（显示前 ${shown.length} 条）` : ''}
        </span>
      </div>

      <div className="three-pane">
        <div className="pane">
          <div className="pane__head">候选队列</div>
          <div className="pane__body" style={{ padding: 0 }}>
            {visible.length === 0 ? (
              <div style={{ padding: 14 }}>
                <Empty
                  title={relations.length === 0 ? '这个课题还没有候选关系' : '这一档没有关系'}
                  body={
                    relations.length === 0
                      ? '先去「文献库」读入自己的论文，或把全文知识库里的领域接入课题，候选关系会出现在这里。'
                      : '换个筛选或搜索词看看。'
                  }
                />
              </div>
            ) : (
              <>
                {shown.map((relation) => (
                  <button
                    key={relation.relation_id}
                    type="button"
                    className={`list__row${current?.relation_id === relation.relation_id ? ' is-active' : ''}`}
                    onClick={() => setSelectedId(relation.relation_id)}
                  >
                    <strong>{relation.source_name} → {relation.target_name}</strong>
                    <Meta
                      items={[
                        relation.relation_type,
                        relation.decision ? DECISION_LABEL[relation.decision] : '待决定',
                        `${relation.evidence_count} 条证据`,
                      ]}
                    />
                  </button>
                ))}
                {visible.length > shown.length ? (
                  <div style={{ padding: '10px 14px' }}>
                    <p className="note">
                      命中 {visible.length} 条，列表只渲染前 {shown.length} 条。
                      用上面的搜索或机器状态筛一下，能更快找到要审的那几条。
                    </p>
                  </div>
                ) : null}
              </>
            )}
          </div>
        </div>

        <div className="pane">
          <div className="pane__head">原文证据</div>
          <div className="pane__body">
            {current ? (
              <>
                <p className="quote">
                  {current.source_name} —{current.relation_type}→ {current.target_name}
                </p>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  <StatusTag status={current.machine_status} />
                  {current.decision ? (
                    <span className={`tag ${DECISION_TONE[current.decision]}`}>
                      {DECISION_LABEL[current.decision]}
                    </span>
                  ) : (
                    <span className="tag tag--plain">你还没决定</span>
                  )}
                  <span className="tag tag--plain tag--mono">{current.relation_id}</span>
                </div>
                <EvidenceList spans={spans} />
              </>
            ) : (
              <Empty title="没有可看的关系" body="换一个筛选，或者先去文献库读入论文。" />
            )}
          </div>
        </div>

        <div className="pane">
          <div className="pane__head">入图决定</div>
          <div className="pane__body">
            <dl className="kv">
              <dt>机器状态</dt>
              <dd>{current ? <StatusTag status={current.machine_status} /> : '—'}</dd>
              <dt>原文证据</dt>
              <dd>{spans.length > 0 ? `${spans.length} 条片段` : '无法定位'}</dd>
              <dt>你的决定</dt>
              <dd>{current?.decision ? DECISION_LABEL[current.decision] : '未决定'}</dd>
            </dl>

            <label className="field">
              <span>给这条决定留一句理由（可留空）</span>
              <textarea
                rows={3}
                value={note}
                onChange={(event) => setNote(event.target.value)}
                placeholder="例如：原文只说了「相关」，没说因果，先暂缓。"
              />
            </label>

            <div style={{ display: 'grid', gap: 8 }}>
              <button type="button" className="btn btn--primary" onClick={() => void decide('include')} disabled={!current || busy}>
                加入我的图谱 <Keycap>A</Keycap>
              </button>
              <button type="button" className="btn" onClick={() => void decide('defer')} disabled={!current || busy}>
                暂缓 <Keycap>S</Keycap>
              </button>
              <button type="button" className="btn btn--quiet" onClick={() => void decide('exclude')} disabled={!current || busy}>
                排除 <Keycap>X</Keycap>
              </button>
            </div>

            <p className="note" style={{ marginTop: 4, display: 'flex', alignItems: 'center', gap: 6 }}>
              <Keycap>J</Keycap><Keycap>K</Keycap> 上下切换
              <InfoTip label="你的决定记在哪">
                你的决定只影响这个课题里的图谱，和人工标注是两回事，各记各的。
              </InfoTip>
            </p>
          </div>
        </div>
      </div>

      {toast ? (
        <Toast
          text={toast.text}
          action={{ label: '撤销', run: () => void undo(toast.relationId) }}
          onDone={() => setToast(null)}
        />
      ) : null}
    </>
  )
}

/** 知识图谱：显示当前课题已纳入的关系与节点，边数严格等于纳入关系数。 */
export function ProjectGraphPage() {
  const { active } = useProject()
  const [graph, setGraph] = useState<ProjectGraph | null>(null)
  const [focus, setFocus] = useState('')
  const [view, setView] = useState<'map' | 'time'>('map')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const projectId = active?.project_id ?? ''

  useEffect(() => {
    if (!projectId) return
    let alive = true
    setLoading(true)
    getProjectGraph(projectId)
      .then((result) => {
        if (!alive) return
        setGraph(result)
        setError(null)
      })
      .catch((err: Error) => { if (alive) setError(err.message) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [projectId])

  const nodes = graph?.nodes ?? []
  const edges = graph?.edges ?? []
  const current = nodes.find((item) => item.id === focus) ?? nodes[0]
  const related = current
    ? edges.filter((edge) => edge.source_name === current.id || edge.target_name === current.id)
    : []

  // 时间视图：按你决定「加入」的月份分组；没有决定时间的归到「时间未记录」。
  const timeline = useMemo(() => {
    const groups = new Map<string, typeof edges>()
    for (const edge of edges) {
      const raw = String(edge.decided_at ?? '')
      const label = raw ? raw.slice(0, 7) : '时间未记录'
      groups.set(label, [...(groups.get(label) ?? []), edge])
    }
    return Array.from(groups.entries())
      .sort((left, right) => (left[0] < right[0] ? 1 : -1))
      .map(([label, rows]) => ({ label, rows }))
  }, [edges])

  const width = 640
  const height = 360
  const radius = Math.min(width, height) / 2 - 62

  if (!active) {
    return (
      <>
        <PageHead title="知识图谱" summary="这里只显示你已经纳入自己图谱的关系。" />
        <InlineNotice />
      </>
    )
  }

  const counts = graph?.counts

  return (
    <>
      <PageHead
        title="知识图谱"
        summary="你纳入的关系和它们连着的实体。"
      />

      {error ? <Empty title="取数失败" body={error} danger /> : null}

      <div className="stats" role="list" style={{ marginBottom: 22 }}>
        <div>
          <dt>已纳入关系</dt>
          <dd className="num">{counts ? counts.included : '—'}</dd>
          
        </div>
        <div>
          <dt>节点</dt>
          <dd className="num">{counts ? counts.nodes : '—'}</dd>
          
        </div>
        <div>
          <dt>待决定</dt>
          <dd className="num">{counts ? counts.undecided : '—'}</dd>
          
        </div>
        <div>
          <dt>暂缓 / 排除</dt>
          <dd className="num">{counts ? `${counts.defer} / ${counts.exclude}` : '—'}</dd>
          
        </div>
      </div>

      <div className="toolbar" style={{ marginBottom: 14 }}>
        <button
          type="button"
          className={view === 'map' ? 'btn btn--primary btn--sm' : 'btn btn--quiet btn--sm'}
          onClick={() => setView('map')}
          aria-pressed={view === 'map'}
        >
          关系地图
        </button>
        <button
          type="button"
          className={view === 'time' ? 'btn btn--primary btn--sm' : 'btn btn--quiet btn--sm'}
          onClick={() => setView('time')}
          aria-pressed={view === 'time'}
        >
          时间视图
        </button>
        <span className="note">
          {view === 'map'
            ? '按实体看邻域：谁和谁相连、连的是什么关系'
            : '按你决定纳入的时间分组'}
        </span>
      </div>

      {loading && !graph ? (
        <Empty title="正在读取图谱" body="读取一次抽取缓存，稍等。" />
      ) : nodes.length === 0 ? (
        <Empty
          title="图谱还是空的"
          body="去「构建图谱」把有用的关系逐条加入，加入之后这里才会有节点和边。"
        />
      ) : view === 'time' ? (
        <div className="timeline">
          {timeline.length === 0 ? (
            <Empty title="还没有时间线" body="关系纳入之后会按你决定的时间分组。" />
          ) : (
            timeline.map((group) => (
              <div className="timeline__month" key={group.label}>
                <div className="timeline__label">
                  {group.label} · {group.rows.length} 条关系
                </div>
                {group.rows.map((edge) => (
                  <div className="timeline__row" key={edge.relation_id}>
                    <strong style={{ fontSize: 14 }}>
                      {edge.source_name} —{edge.relation_type}→ {edge.target_name}
                    </strong>
                    <Meta
                      items={[
                        edge.paper_id,
                        edge.evidence_count ? `${edge.evidence_count} 条证据` : '无证据片段',
                        `决定于 ${String(edge.decided_at ?? '').slice(0, 10)}`,
                      ]}
                    />
                  </div>
                ))}
              </div>
            ))
          )}
        </div>
      ) : (
        <div className="grid-2" style={{ alignItems: 'start' }}>
          <div>
            <SectionHead title={`${current?.label ?? ''} 的邻域`} hint={`${related.length} 条关系`} />
            <svg className="neighborhood" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="所选实体的直接关系邻域">
              <circle cx={width / 2} cy={height / 2} r={radius} fill="none" stroke="var(--rule-soft)" />
              {related.slice(0, 14).map((edge, index) => {
                const angle = (2 * Math.PI * index) / Math.max(related.length, 1) - Math.PI / 2
                const x = width / 2 + radius * Math.cos(angle)
                const y = height / 2 + radius * Math.sin(angle)
                const other = edge.source_name === current?.id ? edge.target_name : edge.source_name
                return (
                  <g key={edge.relation_id}>
                    <line x1={width / 2} y1={height / 2} x2={x} y2={y} className="is-evidence" />
                    <g className="node" transform={`translate(${x},${y})`} onClick={() => setFocus(other)} style={{ cursor: 'pointer' }}>
                      <circle r={6} />
                      <text x={0} y={18} textAnchor="middle">
                        {other.length > 18 ? `${other.slice(0, 17)}…` : other}
                      </text>
                    </g>
                  </g>
                )
              })}
              <g className="node node--focus" transform={`translate(${width / 2},${height / 2})`}>
                <circle r={9} />
                <text x={0} y={26} textAnchor="middle" style={{ fontWeight: 600 }}>{current?.label}</text>
              </g>
            </svg>
          </div>

          <div>
            <SectionHead title="已纳入的关系" hint={`共 ${edges.length} 条`} />
            <div className="list list--scroll" role="list" style={{ maxHeight: 420 }}>
              {edges.map((edge) => (
                <div className="list__row" key={edge.relation_id}>
                  <strong>{edge.source_name} —{edge.relation_type}→ {edge.target_name}</strong>
                  <Meta
                    items={[
                      edge.decision ? DECISION_LABEL[edge.decision] : '',
                      edge.paper_id,
                      edge.evidence_count ? `${edge.evidence_count} 条证据` : '无证据片段',
                    ]}
                  />
                </div>
              ))}
            </div>
            <div style={{ marginTop: 14, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {nodes.slice(0, 12).map((node) => (
                <button
                  key={node.id}
                  type="button"
                  className={current?.id === node.id ? 'tag tag--accepted' : 'tag tag--plain'}
                  onClick={() => setFocus(node.id)}
                >
                  {node.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

    </>
  )
}

/** 语料侧工具：图谱问答、图谱洞察、在线检索。
 *
 *  这三样都跑在**公共语料**上，不属于"我的课题图谱"，也不会把结果写进个人图谱；
 *  页面上把这条边界写在标题里，避免读者把检索结果当成自己纳入的关系。 */
export function EvidenceCenterPage() {
  const { active } = useProject()
  const [graph, setGraph] = useState<ProjectGraph | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [openKey, setOpenKey] = useState<string | null>(null)
  const [contexts, setContexts] = useState<Record<string, EvidenceContextPayload>>({})
  const [contextBusy, setContextBusy] = useState('')
  const [contextError, setContextError] = useState<string | null>(null)

  const projectId = active?.project_id ?? ''

  const loadContext = async (evidenceId: string) => {
    if (!projectId) return
    setContextBusy(evidenceId)
    setContextError(null)
    try {
      const payload = await getEvidenceContext(projectId, evidenceId, 400)
      setContexts((current) => ({ ...current, [evidenceId]: payload }))
    } catch (err) {
      setContextError(err instanceof Error ? err.message : String(err))
    } finally {
      setContextBusy('')
    }
  }

  useEffect(() => {
    if (!projectId) return
    let alive = true
    getProjectGraph(projectId)
      .then((result) => { if (alive) { setGraph(result); setError(null) } })
      .catch((err: Error) => { if (alive) setError(err.message) })
    return () => { alive = false }
  }, [projectId])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpenKey(null) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  if (!active) {
    return (
      <>
        <PageHead title="证据中心" summary="逐条读证据片段，看到它在原文里的哪一段、哪个字符区间。" />
        <InlineNotice />
      </>
    )
  }

  const edges = graph?.edges ?? []
  const evidence = graph?.evidence ?? {}
  const rows = edges.flatMap((edge) =>
    (evidence[edge.relation_id] ?? []).map((span) => ({ edge, span })),
  )

  return (
    <>
      <PageHead
        title="证据中心"
        summary="已纳入关系引用的原文片段。"
      />

      {error ? <Empty title="取数失败" body={error} danger /> : null}

      {rows.length === 0 ? (
        <Empty
          title="还没有可读的证据片段"
          body="证据中心只显示已纳入关系引用的片段。先去「构建图谱」把关系加入，或去「文献库」读入论文。"
        />
      ) : (
        <>
          <div className="toolbar">
            <span className="note">共 {rows.length} 条片段，来自 {edges.length} 条已纳入关系。</span>
          </div>
          <div className="list">
            {rows.map(({ edge, span }) => {
              const key = `${edge.relation_id}:${span.evidence_id}`
              const isOpen = openKey === key
              return (
                <div className="list__row" key={key} style={{ cursor: 'default' }}>
                  <strong>
                    {edge.source_name} —{edge.relation_type}→ {edge.target_name}
                  </strong>
                  <p className="evi__excerpt" style={{ margin: '4px 0 6px' }}>
                    {span.text || '（只存了位置，没有片段正文）'}
                  </p>
                  <div className="evi__row">
                    <span className="evidence__meta" style={{ marginTop: 0 }}>
                      <span>{span.paper_id}</span>
                      <span>{span.section_id || '未标段落'}</span>
                      <span>{span.char_start}–{span.char_end}</span>
                    </span>
                    <button
                      type="button"
                      className="evi__chip"
                      aria-expanded={isOpen}
                      onMouseEnter={() => setOpenKey(key)}
                      onFocus={() => setOpenKey(key)}
                      onMouseLeave={() => setOpenKey((value) => (value === key ? null : value))}
                      onBlur={() => setOpenKey((value) => (value === key ? null : value))}
                      onClick={() => setOpenKey(isOpen ? null : key)}
                    >
                      查看定位
                    </button>
                  </div>
                  {isOpen ? (
                    <div className="evi-pop" role="dialog" aria-label="证据定位">
                      <div className="evi-pop__head">
                        <strong>证据定位</strong>
                        <button type="button" className="evi-pop__close" onClick={() => setOpenKey(null)} aria-label="关闭">
                          ×
                        </button>
                      </div>
                      <p className="quote">{span.text || '（没有存储片段正文）'}</p>
                      <dl className="kv" style={{ marginTop: 10 }}>
                        <dt>论文</dt>
                        <dd className="mono">{span.paper_id}</dd>
                        <dt>段落</dt>
                        <dd className="mono">{span.section_id || '未标注'}</dd>
                        <dt>字符区间</dt>
                        <dd className="mono">{span.char_start}–{span.char_end}</dd>
                        <dt>挂在</dt>
                        <dd className="mono">{edge.relation_id}</dd>
                      </dl>

                      <div className="toolbar" style={{ marginTop: 10, marginBottom: 0 }}>
                        <button
                          type="button"
                          className="btn btn--quiet btn--sm"
                          onClick={() => void loadContext(span.evidence_id)}
                          disabled={contextBusy === span.evidence_id}
                        >
                          {contextBusy === span.evidence_id ? '取上下文中…' : '取回前后文'}
                        </button>
                        <span className="note">调用 /api/evidence/{span.evidence_id}/context</span>
                      </div>

                      {contexts[span.evidence_id] ? (
                        <div style={{ marginTop: 10 }}>
                          {contexts[span.evidence_id].source === 'unavailable' ? (
                            <p className="note">{contexts[span.evidence_id].note}</p>
                          ) : (
                            <>
                              <p className="evi__excerpt" style={{ whiteSpace: 'pre-wrap' }}>
                                {contexts[span.evidence_id].context}
                              </p>
                              <p className="note" style={{ marginTop: 6 }}>
                                {contexts[span.evidence_id].note}
                                （片段位于全文第 {contexts[span.evidence_id].char_start}–
                                {contexts[span.evidence_id].char_end} 字符）
                              </p>
                            </>
                          )}
                        </div>
                      ) : null}
                      {contextError ? (
                        <p className="note" style={{ color: 'var(--danger)', marginTop: 8 }}>{contextError}</p>
                      ) : null}

                      <p className="note" style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                        <InfoTip label="片段与正文的区别">
                          这里只是引用片段。整篇正文只有你在读入时主动勾选才会保存。
                        </InfoTip>
                      </p>
                    </div>
                  ) : null}
                </div>
              )
            })}
          </div>
        </>
      )}
    </>
  )
}
