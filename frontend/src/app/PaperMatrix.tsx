import { useCallback, useEffect, useMemo, useState } from 'react'
import { getProjectGraph, getProjectPapers, getProjectRelations } from '../api'
import type { ProjectGraph, ProjectPaper, ProjectRelation } from '../types'
import { useProject } from './project'
import { Empty, Meta, SectionHead } from './ui'

/** 论文对照矩阵：把课题里的论文按同一批字段横向对齐，点一行看这篇带出来的关系。
 *
 *  列可以自己加减；没有的字段显示「—」而不是留空，免得看不出是"没有"还是"没读到"。
 *  点某一行之后，右侧只显示这一篇带出来的候选关系与证据条数——**不显示别的论文的证据**。 */

type ColumnKey = 'source' | 'added' | 'candidates' | 'included' | 'evidence'

const COLUMNS: Array<{ key: ColumnKey; label: string }> = [
  { key: 'source', label: '来源' },
  { key: 'added', label: '加入时间' },
  { key: 'candidates', label: '候选关系' },
  { key: 'included', label: '已纳入' },
  { key: 'evidence', label: '证据片段' },
]

const DEFAULT_COLUMNS: ColumnKey[] = ['source', 'candidates', 'included', 'evidence']

function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  return value.slice(0, 19).replace('T', ' ')
}

export function PaperMatrix() {
  const { active } = useProject()
  const projectId = active?.project_id ?? ''
  const [papers, setPapers] = useState<ProjectPaper[]>([])
  const [relations, setRelations] = useState<ProjectRelation[]>([])
  const [graph, setGraph] = useState<ProjectGraph | null>(null)
  const [columns, setColumns] = useState<ColumnKey[]>(DEFAULT_COLUMNS)
  const [focus, setFocus] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async (id: string) => {
    if (!id) {
      setPapers([])
      setRelations([])
      setGraph(null)
      return
    }
    setLoading(true)
    try {
      const [paperRows, relationRows, graphPayload] = await Promise.all([
        getProjectPapers(id),
        getProjectRelations(id),
        getProjectGraph(id),
      ])
      setPapers(paperRows)
      setRelations(relationRows.relations ?? [])
      setGraph(graphPayload)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load(projectId)
  }, [load, projectId])

  const rows = useMemo(() => {
    const includedIds = new Set((graph?.edges ?? []).map((edge) => edge.relation_id))
    return papers.map((paper) => {
      const own = relations.filter((relation) => relation.paper_id === paper.paper_id)
      return {
        paper,
        candidates: own.length,
        included: own.filter((relation) => includedIds.has(relation.relation_id)).length,
        evidence: own.reduce((sum, relation) => sum + (relation.evidence_count ?? 0), 0),
        own,
      }
    })
  }, [papers, relations, graph])

  const current = rows.find((row) => row.paper.paper_id === focus) ?? null

  const toggle = (key: ColumnKey) => {
    setColumns((current) => {
      if (current.includes(key)) {
        // 至少留一列，全关掉就没意义了
        return current.length === 1 ? current : current.filter((item) => item !== key)
      }
      return COLUMNS.map((column) => column.key).filter(
        (item) => current.includes(item) || item === key,
      )
    })
  }

  if (!projectId) return null

  return (
    <div className="section">
      <SectionHead
        title="论文对照矩阵"
        hint={loading ? '读取中…' : `${papers.length} 篇`}
      />

      <div className="toolbar">
        <span className="note">显示的列：</span>
        {COLUMNS.map((column) => (
          <button
            key={column.key}
            type="button"
            className={columns.includes(column.key) ? 'tag tag--accepted' : 'tag tag--plain'}
            onClick={() => toggle(column.key)}
            aria-pressed={columns.includes(column.key)}
          >
            {column.label}
          </button>
        ))}
        <span style={{ flex: 1 }} />
        <button type="button" className="btn btn--quiet btn--sm" onClick={() => void load(projectId)}>
          刷新
        </button>
      </div>

      {error ? <Empty title="对照表取数失败" body={error} danger /> : null}

      {papers.length === 0 && !loading ? (
        <Empty
          title="这个课题还没有论文"
          body="去「文献库」读入自己的论文，或者在语料目录里把一篇加入当前课题；加入之后这里会出现对照表。"
        />
      ) : (
        <div className="matrix-wrap">
          <table className="matrix">
            <thead>
              <tr>
                <th scope="col">论文</th>
                {COLUMNS.filter((column) => columns.includes(column.key)).map((column) => (
                  <th scope="col" key={column.key}>{column.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.paper.paper_id}
                  className={focus === row.paper.paper_id ? 'is-active' : undefined}
                  onClick={() =>
                    setFocus((current) => (current === row.paper.paper_id ? '' : row.paper.paper_id))
                  }
                  tabIndex={0}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      setFocus((current) => (current === row.paper.paper_id ? '' : row.paper.paper_id))
                    }
                  }}
                  aria-selected={focus === row.paper.paper_id}
                >
                  <th scope="row">
                    <strong>{row.paper.title || row.paper.paper_id}</strong>
                    <span className="matrix__sub mono">{row.paper.paper_id}</span>
                  </th>
                  {columns.includes('source') ? <td>{row.paper.source_kind || '—'}</td> : null}
                  {columns.includes('added') ? <td>{formatDate(row.paper.added_at)}</td> : null}
                  {columns.includes('candidates') ? <td className="num">{row.candidates}</td> : null}
                  {columns.includes('included') ? <td className="num">{row.included}</td> : null}
                  {columns.includes('evidence') ? <td className="num">{row.evidence}</td> : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {current ? (
        <div className="panel" style={{ marginTop: 12 }}>
          <div className="panel__body">
            <SectionHead
              title={current.paper.title || current.paper.paper_id}
              hint={`${current.own.length} 条候选 · ${current.evidence} 条证据片段`}
            />
            {current.own.length === 0 ? (
              <p className="note">这篇还没有抽取出候选关系。可能是只记了归属，还没有跑过导入。</p>
            ) : (
              <div className="list list--scroll" style={{ maxHeight: 260 }}>
                {current.own.map((relation) => (
                  <div className="list__row" key={relation.relation_id} style={{ cursor: 'default' }}>
                    <strong>
                      {relation.source_name} —{relation.relation_type}→ {relation.target_name}
                    </strong>
                    <Meta
                      items={[
                        `机器状态：${relation.machine_status}`,
                        relation.decision ? `你的决定：${relation.decision}` : '还没决定',
                        relation.evidence_count ? `${relation.evidence_count} 条证据片段` : '没有证据片段',
                      ]}
                    />
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="panel__foot">
            这里只显示这一篇带出来的关系，不混别的论文；要改决定请到「构建图谱」，要读原文请到「证据中心」。
          </div>
        </div>
      ) : null}
    </div>
  )
}
