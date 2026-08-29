import { useCallback, useEffect, useMemo, useState } from 'react'
import { getAtlasDomain, getAtlasDomains } from '../api'
import type { AtlasDomainData, AtlasDomainSummary, AtlasEntity, AtlasPaper } from '../types'
import AtlasGraph from './AtlasGraph'
import './atlas.css'

const TYPE_COLORS: Record<string, string> = {
  METHOD: '#a51931', TASK: '#1f4e79', DATASET: '#2d6a4f', METRIC: '#b8860b',
  FINDING: '#c0531e', LIMITATION: '#7a756d', DOMAIN: '#6b4c8a', PAPER: '#2b2620',
}
const TYPE_LABELS: Record<string, string> = {
  METHOD: '方法', TASK: '任务', DATASET: '数据集', METRIC: '指标',
  FINDING: '发现', LIMITATION: '局限', DOMAIN: '领域', PAPER: '论文',
}
const REL_COLORS: Record<string, string> = {
  IMPROVES: '#2d6a4f', ENABLES: '#1f4e79', USES: '#8b8680',
  EVALUATES_ON: '#2a7b8c', REPORTS: '#b8860b', SUPPORTS: '#2d6a4f',
  CONTRADICTS: '#c0392b', EXTENDS: '#a51931', ADDRESSES: '#6b4c8a',
  BENCHMARKS: '#2a7b8c', RELATED_TO: '#cfc8bc',
}
const REL_LABELS: Record<string, string> = {
  IMPROVES: '改善', ENABLES: '使能', USES: '使用', EVALUATES_ON: '评测于',
  REPORTS: '报告', SUPPORTS: '支持', CONTRADICTS: '矛盾', EXTENDS: '扩展',
  ADDRESSES: '针对', BENCHMARKS: '基准', RELATED_TO: '相关',
}

type Selection = { kind: 'paper'; id: string } | { kind: 'entity'; id: string } | null

export default function AtlasPage({ onExit }: { onExit: () => void }) {
  const [domains, setDomains] = useState<AtlasDomainSummary[]>([])
  const [domainId, setDomainId] = useState<string>('')
  const [data, setData] = useState<AtlasDomainData | null>(null)
  const [view, setView] = useState<'force' | 'timeline'>('force')
  const [search, setSearch] = useState('')
  const [yearMin, setYearMin] = useState<string>('')
  const [yearMax, setYearMax] = useState<string>('')
  const [sortBy, setSortBy] = useState('citation_desc')
  const [tiers, setTiers] = useState({ evidence_card: true, metadata_only: true })
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set())
  const [selection, setSelection] = useState<Selection>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [leftCollapsed, setLeftCollapsed] = useState(false)
  const [rightCollapsed, setRightCollapsed] = useState(false)

  useEffect(() => {
    getAtlasDomains()
      .then((res) => {
        setDomains(res.domains)
        const qc = res.domains.find((d) => d.domain_id === 'quantum-computing')
        setDomainId(qc?.domain_id ?? res.domains[0]?.domain_id ?? '')
      })
      .catch((err) => setError(err.message))
  }, [])

  useEffect(() => {
    if (!domainId) return
    setLoading(true)
    setSelection(null)
    getAtlasDomain(domainId)
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [domainId])

  const filteredPapers = useMemo(() => {
    if (!data) return []
    let list = [...data.papers]
    if (search) {
      const q = search.toLowerCase()
      list = list.filter((p) =>
        p.title.toLowerCase().includes(q) ||
        p.authors.some((a) => a.toLowerCase().includes(q)) ||
        p.concepts.some((c) => c.toLowerCase().includes(q)),
      )
    }
    if (yearMin) list = list.filter((p) => p.year >= parseInt(yearMin))
    if (yearMax) list = list.filter((p) => p.year <= parseInt(yearMax))
    list = list.filter((p) => tiers[p.evidence_tier as keyof typeof tiers])
    const sorters: Record<string, (a: AtlasPaper, b: AtlasPaper) => number> = {
      citation_desc: (a, b) => b.citation_count - a.citation_count,
      citation_asc: (a, b) => a.citation_count - b.citation_count,
      year_desc: (a, b) => b.year - a.year || b.citation_count - a.citation_count,
      year_asc: (a, b) => a.year - b.year || b.citation_count - a.citation_count,
      title_asc: (a, b) => a.title.localeCompare(b.title),
    }
    list.sort(sorters[sortBy])
    return list
  }, [data, search, yearMin, yearMax, sortBy, tiers])

  const entityTypes = useMemo(
    () => data ? [...new Set(data.entities.map((e) => e.entity_type))].sort() : [],
    [data],
  )

  const selectPaper = useCallback((id: string) => setSelection({ kind: 'paper', id }), [])
  const selectEntity = useCallback((id: string) => setSelection({ kind: 'entity', id }), [])

  const toggleType = (t: string) => {
    setHiddenTypes((prev) => {
      const next = new Set(prev)
      if (next.has(t)) next.delete(t)
      else next.add(t)
      return next
    })
  }

  if (error) return <div className="atlas-root" style={{ padding: 40, color: '#c0392b' }}>加载失败: {error}</div>

  return (
    <div className="atlas-root">
      {/* Masthead */}
      <header className="atlas-masthead">
        <div className="atlas-masthead__inner">
          <button
            onClick={onExit}
            style={{
              background: 'none', border: '1px solid var(--border-strong)', borderRadius: 2,
              padding: '4px 10px', fontSize: 12, cursor: 'pointer', color: 'var(--ink-muted)',
              flexShrink: 0,
            }}
            title="返回研究工作台"
          >
            ← 返回
          </button>
          <div className="atlas-masthead__brand">
            <div className="atlas-masthead__logo">研</div>
            <div>
              <div className="atlas-masthead__title">研海寻踪</div>
              <div className="atlas-masthead__subtitle">Evidence-Grounded Research Intelligence</div>
            </div>
          </div>
          <nav className="atlas-domain-tabs">
            {domains.map((d) => (
              <button
                key={d.domain_id}
                className={`atlas-domain-tab ${d.domain_id === domainId ? 'is-active' : ''}`}
                onClick={() => setDomainId(d.domain_id)}
              >
                <span className="atlas-domain-tab__name">{d.domain_name}</span>
                <span className="atlas-domain-tab__count">{d.paper_count} 篇 · {d.entity_count} 实体 · {d.relation_count} 关系</span>
              </button>
            ))}
          </nav>
          <div className="atlas-view-toggle">
            <button className={view === 'force' ? 'is-active' : ''} onClick={() => setView('force')}>力导向</button>
            <button className={view === 'timeline' ? 'is-active' : ''} onClick={() => setView('timeline')}>时间轴</button>
          </div>
        </div>
        <div className="atlas-masthead__meta">
          <span>{data?.domain_name ?? '—'}</span>
          <span className="atlas-masthead__sep">·</span>
          <span>{data ? `${data.papers.length} 篇文献 · ${data.entities.length} 实体 · ${data.relations.length} 关系 · ${Object.keys(data.cards).length} 证据卡` : '加载中'}</span>
          <span className="atlas-masthead__date">27 AUGUST 2026</span>
        </div>
      </header>

      {/* Body */}
      <div className="atlas-body">
        {/* Left: paper list */}
        <aside className={`atlas-panel atlas-panel--left ${leftCollapsed ? 'is-collapsed' : ''}`}>
          <div className="atlas-panel__header">
            <h2>文献索引</h2>
            <button className="atlas-panel__collapse" onClick={() => setLeftCollapsed(!leftCollapsed)}>‹</button>
          </div>
          <div className="atlas-panel__body">
            <div className="atlas-search">
              <input placeholder="搜索标题、作者、方法…" value={search} onChange={(e) => setSearch(e.target.value)} />
            </div>
            <div className="atlas-filter-row">
              <span className="atlas-filter-label">年份</span>
              <div className="atlas-year-range">
                <input type="number" placeholder="2015" value={yearMin} onChange={(e) => setYearMin(e.target.value)} />
                <span>—</span>
                <input type="number" placeholder="2026" value={yearMax} onChange={(e) => setYearMax(e.target.value)} />
              </div>
            </div>
            <div className="atlas-filter-row">
              <span className="atlas-filter-label">排序</span>
              <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
                <option value="citation_desc">引用量 ↓</option>
                <option value="citation_asc">引用量 ↑</option>
                <option value="year_desc">年份 ↓</option>
                <option value="year_asc">年份 ↑</option>
                <option value="title_asc">标题 A-Z</option>
              </select>
            </div>
            <div className="atlas-filter-row">
              <span className="atlas-filter-label">层级</span>
              <div className="atlas-tier-toggle">
                <label><input type="checkbox" checked={tiers.evidence_card} onChange={(e) => setTiers({ ...tiers, evidence_card: e.target.checked })} /> 证据卡</label>
                <label><input type="checkbox" checked={tiers.metadata_only} onChange={(e) => setTiers({ ...tiers, metadata_only: e.target.checked })} /> 元数据</label>
              </div>
            </div>
            <div className="atlas-legend">
              {entityTypes.map((t) => (
                <span key={t} className={`atlas-legend-item ${hiddenTypes.has(t) ? 'is-off' : ''}`} onClick={() => toggleType(t)}>
                  <span className="atlas-legend-dot" style={{ background: TYPE_COLORS[t] ?? '#999' }} />
                  {TYPE_LABELS[t] ?? t}
                </span>
              ))}
            </div>
            <div className="atlas-paper-list">
              {filteredPapers.map((p) => (
                <div
                  key={p.paper_id}
                  className={`atlas-paper-item ${selection?.kind === 'paper' && selection.id === p.paper_id ? 'is-active' : ''}`}
                  onClick={() => selectPaper(p.paper_id)}
                >
                  <div className="atlas-paper-item__title">{p.title}</div>
                  <div className="atlas-paper-item__meta">
                    <span className={`atlas-tier-badge atlas-tier-badge--${p.evidence_tier === 'evidence_card' ? 'evidence' : 'metadata'}`}>
                      {p.evidence_tier === 'evidence_card' ? '证据卡' : '元数据'}
                    </span>
                    <span className="atlas-paper-item__venue">{p.venue}</span>
                    <span className="atlas-paper-item__year">{p.year}</span>
                    <span className="atlas-paper-item__cites">{p.citation_count}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </aside>

        {/* Center: graph */}
        <section className="atlas-panel atlas-panel--center">
          {data && !loading && (
            <div className="atlas-canvas">
              <AtlasGraph
                key={view}
                data={data}
                view={view}
                hiddenTypes={hiddenTypes}
                onSelectPaper={selectPaper}
                onSelectEntity={selectEntity}
              />
            </div>
          )}
          <div className="atlas-hint">
            <kbd>滚轮</kbd>缩放 · <kbd>拖拽</kbd>平移 · <kbd>点击节点</kbd>查看详情
          </div>
          {loading && (
            <div className="atlas-loading">
              <div className="atlas-loading__spinner" />
              <span>正在构建证据图谱…</span>
            </div>
          )}
        </section>

        {/* Right: detail */}
        <aside className={`atlas-panel atlas-panel--right ${rightCollapsed ? 'is-collapsed' : ''}`}>
          <div className="atlas-panel__header">
            <h2>详情</h2>
            <button className="atlas-panel__collapse" onClick={() => setRightCollapsed(!rightCollapsed)}>›</button>
          </div>
          <div className="atlas-panel__body">
            {data && selection ? (
              selection.kind === 'paper'
                ? <PaperDetail paperId={selection.id} data={data} onSelectEntity={selectEntity} />
                : <EntityDetail entityId={selection.id} data={data} onSelectEntity={selectEntity} onSelectPaper={selectPaper} />
            ) : (
              <div className="atlas-detail-empty">
                <div className="atlas-detail-empty__icon">◎</div>
                <p>点击图谱中的节点或左侧文献<br />查看论文元数据与证据卡</p>
              </div>
            )}
          </div>
        </aside>
      </div>

      {/* Status bar */}
      <footer className="atlas-statusbar">
        <span>节点 {view === 'force' ? data?.entities.filter((e) => !hiddenTypes.has(e.entity_type)).length ?? 0 : filteredPapers.length}</span>
        <span className="atlas-statusbar__sep">|</span>
        <span>关系 {view === 'force' ? data?.relations.length ?? 0 : 0}</span>
        <span className="atlas-statusbar__sep">|</span>
        <span>证据跨度 {data?.evidence.length ?? 0}</span>
        <span className="atlas-statusbar__sep">|</span>
        <span>{selection ? `选中: ${selection.kind === 'paper' ? data?.papers.find((p) => p.paper_id === selection.id)?.title.slice(0, 30) : data?.entities.find((e) => e.entity_id === selection.id)?.canonical_name}` : '未选中'}</span>
        <span className="atlas-statusbar__right">研海寻踪 · YANHAI TRACE · Evidence before assertion</span>
      </footer>
    </div>
  )
}

// ─── Paper detail ───

function PaperDetail({ paperId, data, onSelectEntity }: {
  paperId: string
  data: AtlasDomainData
  onSelectEntity: (id: string) => void
}) {
  const p = data.papers.find((x) => x.paper_id === paperId)
  if (!p) return null
  const card = data.cards[paperId]
  const entityIds = data.paper_entities[paperId] ?? []
  const entities = entityIds.map((id) => data.entities.find((e) => e.entity_id === id)).filter(Boolean) as AtlasEntity[]

  return (
    <div>
      <div className="atlas-detail-section">
        <div className="atlas-detail-section__title">{p.evidence_tier === 'evidence_card' ? '证据卡论文' : '元数据记录'}</div>
        <h2 className="atlas-detail-title">{p.title}</h2>
        <div className="atlas-detail-meta">
          <div className="atlas-detail-meta__row"><span className="atlas-detail-meta__label">作者</span><span className="atlas-detail-meta__value">{p.authors.slice(0, 6).join(', ')}{p.authors.length > 6 ? ' 等' : ''}</span></div>
          <div className="atlas-detail-meta__row"><span className="atlas-detail-meta__label">期刊</span><span className="atlas-detail-meta__value" style={{ color: 'var(--nature-red)', fontWeight: 600 }}>{p.venue}</span></div>
          <div className="atlas-detail-meta__row"><span className="atlas-detail-meta__label">年份</span><span className="atlas-detail-meta__value">{p.year}</span></div>
          {p.doi && <div className="atlas-detail-meta__row"><span className="atlas-detail-meta__label">DOI</span><span className="atlas-detail-meta__value"><a href={`https://doi.org/${p.doi}`} target="_blank" rel="noopener noreferrer">{p.doi}</a></span></div>}
          <div className="atlas-detail-meta__row"><span className="atlas-detail-meta__label">引用</span><span className="atlas-detail-meta__value">{p.citation_count}（OpenAlex 快照）</span></div>
        </div>
        <div className="atlas-detail-stats">
          <div className="atlas-detail-stat"><div className="atlas-detail-stat__num">{entities.length}</div><div className="atlas-detail-stat__label">涉及实体</div></div>
          <div className="atlas-detail-stat"><div className="atlas-detail-stat__num">{card ? '✓' : '—'}</div><div className="atlas-detail-stat__label">证据卡</div></div>
          <div className="atlas-detail-stat"><div className="atlas-detail-stat__num">{p.concepts.length}</div><div className="atlas-detail-stat__label">概念</div></div>
        </div>
      </div>
      {card && (
        <div className="atlas-detail-section">
          <div className="atlas-detail-section__title">证据卡（基于公开摘要释义）</div>
          <div className="atlas-card" dangerouslySetInnerHTML={{ __html: renderCard(card) }} />
        </div>
      )}
      {entities.length > 0 && (
        <div className="atlas-detail-section">
          <div className="atlas-detail-section__title">涉及实体（点击查看）</div>
          <div className="atlas-relation-list">
            {entities.map((e) => (
              <div key={e.entity_id} className="atlas-relation-item" onClick={() => onSelectEntity(e.entity_id)}>
                <span className="atlas-legend-dot" style={{ background: TYPE_COLORS[e.entity_type] ?? '#999' }} />
                <span className="atlas-relation-name">{e.canonical_name}</span>
                <span style={{ color: 'var(--ink-faint)' }}>· {TYPE_LABELS[e.entity_type] ?? e.entity_type}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Entity detail ───

function EntityDetail({ entityId, data, onSelectEntity, onSelectPaper }: {
  entityId: string
  data: AtlasDomainData
  onSelectEntity: (id: string) => void
  onSelectPaper: (id: string) => void
}) {
  const e = data.entities.find((x) => x.entity_id === entityId)
  if (!e) return null
  const rels = data.relations.filter((r) => r.source_id === entityId || r.target_id === entityId)
  const paperIds = Object.entries(data.paper_entities)
    .filter(([, eids]) => eids.includes(entityId))
    .map(([pid]) => pid)
  const papers = paperIds
    .map((pid) => data.papers.find((p) => p.paper_id === pid))
    .filter(Boolean) as AtlasPaper[]
  papers.sort((a, b) => b.citation_count - a.citation_count)

  return (
    <div>
      <div className="atlas-detail-section">
        <div className="atlas-detail-section__title">实体</div>
        <h2 className="atlas-detail-title">
          <span className="atlas-legend-dot" style={{ display: 'inline-block', width: 11, height: 11, background: TYPE_COLORS[e.entity_type] ?? '#999', marginRight: 5, verticalAlign: 'middle' }} />
          {e.canonical_name}
        </h2>
        <div className="atlas-detail-meta">
          <div className="atlas-detail-meta__row"><span className="atlas-detail-meta__label">类型</span><span className="atlas-detail-meta__value">{TYPE_LABELS[e.entity_type] ?? e.entity_type}</span></div>
          <div className="atlas-detail-meta__row"><span className="atlas-detail-meta__label">置信度</span><span className="atlas-detail-meta__value">{(e.confidence * 100).toFixed(0)}%</span></div>
          <div className="atlas-detail-meta__row"><span className="atlas-detail-meta__label">提及</span><span className="atlas-detail-meta__value">{e.mention_count} 次 · {papers.length} 篇论文</span></div>
          {e.aliases.length > 0 && <div className="atlas-detail-meta__row"><span className="atlas-detail-meta__label">别名</span><span className="atlas-detail-meta__value">{e.aliases.slice(0, 8).join(', ')}</span></div>}
        </div>
        <div className="atlas-detail-stats">
          <div className="atlas-detail-stat"><div className="atlas-detail-stat__num">{rels.length}</div><div className="atlas-detail-stat__label">关系</div></div>
          <div className="atlas-detail-stat"><div className="atlas-detail-stat__num">{papers.length}</div><div className="atlas-detail-stat__label">论文</div></div>
          <div className="atlas-detail-stat"><div className="atlas-detail-stat__num">{rels.filter((r) => r.status === 'accepted').length}</div><div className="atlas-detail-stat__label">已接受</div></div>
        </div>
      </div>
      <div className="atlas-detail-section">
        <div className="atlas-detail-section__title">关系（{rels.length}）</div>
        <div className="atlas-relation-list">
          {rels.map((r) => {
            const isSource = r.source_id === entityId
            const otherId = isSource ? r.target_id : r.source_id
            const otherName = isSource ? r.target_name : r.source_name
            return (
              <div key={r.relation_id} className="atlas-relation-item" onClick={() => onSelectEntity(otherId)}>
                <span className="atlas-relation-type" style={{ background: REL_COLORS[r.relation_type] ?? '#999' }}>{REL_LABELS[r.relation_type] ?? r.relation_type}</span>
                <span className="atlas-relation-arrow">{isSource ? '→' : '←'}</span>
                <span className="atlas-relation-name">{otherName}</span>
                <span className="atlas-relation-conf">{(r.confidence * 100).toFixed(0)}%</span>
              </div>
            )
          })}
        </div>
      </div>
      {papers.length > 0 && (
        <div className="atlas-detail-section">
          <div className="atlas-detail-section__title">支持论文（{papers.length}）</div>
          <div className="atlas-relation-list">
            {papers.slice(0, 15).map((p) => (
              <div key={p.paper_id} className="atlas-relation-item" onClick={() => onSelectPaper(p.paper_id)}>
                <span className={`atlas-tier-badge atlas-tier-badge--${p.evidence_tier === 'evidence_card' ? 'evidence' : 'metadata'}`}>{p.year}</span>
                <span style={{ fontWeight: 400, fontSize: 10 }}>{p.title.slice(0, 55)}{p.title.length > 55 ? '…' : ''}</span>
              </div>
            ))}
            {papers.length > 15 && <div style={{ padding: '5px 0', fontSize: 9, color: 'var(--ink-faint)' }}>…还有 {papers.length - 15} 篇</div>}
          </div>
        </div>
      )}
    </div>
  )
}

function renderCard(md: string): string {
  return md
    .replace(/^#+\s+(.+)$/gm, '<h3>$1</h3>')
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br/>')
    .replace(/^(.+)$/, '<p>$1</p>')
    .replace(/<p><h3>/g, '<h3>')
    .replace(/<\/h3><\/p>/g, '</h3>')
}
