import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ApiError,
  extractPdfTables,
  getIngestion,
  getIngestions,
  getProjectPapers,
  getProjectRelations,
  getSystemAccess,
  ingestPaper,
  ingestPdf,
  removeProjectPaper,
} from '../api'
import type { IngestionSummaryRow, ProjectPaper } from '../types'
import { useProject } from './project'
import { Empty, Meta, PageHead, SectionHead } from './ui'

/** 导入面板：把用户自己的论文读进当前课题。
 *
 *  两条路都走后端已有的 `/api/ingest-paper` 与 `/api/ingest-pdf`；
 *  原文只有勾了"允许保存原文"才会落盘，默认不落。
 *
 *  批量导入是**逐篇发请求**，不是把 20 篇塞进一个请求：单篇失败不影响其余，
 *  进度也能一篇一篇看见。上限（篇数、单篇字节数）从 `/api/system/access` 取，
 *  不在前端另写一份数字。 */

/** 抽取器换过了就说一声：通用抽取出来的候选全要人复核，不能让人以为是精抽。 */
function extractorNote(extractor: unknown): string {
  if (extractor !== 'generic-pattern') return ''
  return ' 这篇论文的术语不在内置词表里，用的是通用抽取：实体名从原文里挖，关系全部要你自己核。'
}

/** 一篇的读入结果只报"真正进了课题多少条"。
 *
 *  不报抽取器的 `candidate_relation_count`：那是抽取阶段的关系数，和进课题的
 *  条数来自两份不同的东西（进课题走三轮裁决后的主张），实测会出现
 *  「候选关系 1 条、进课题 2 条」这种自相矛盾的显示（2026-10-20 在公网抓到）。
 *  论文清单那一栏显示的也是同一个数，两处对得上。 */
function ingestLine(result: {
  summary?: { candidate_relation_count?: number; accepted_count?: number; needs_review_count?: number; extractor?: string }
  persistence?: { project_candidate_count?: number }
}): string {
  const written = result.persistence?.project_candidate_count
  const candidates = result.summary?.candidate_relation_count ?? 0
  const head = written === undefined ? `候选关系 ${candidates} 条` : `进课题 ${written} 条`
  return (
    head +
    `（机器接受 ${result.summary?.accepted_count ?? 0} / 需复核 ${result.summary?.needs_review_count ?? 0}）` +
    extractorNote(result.summary?.extractor)
  )
}

const DEFAULT_LIMITS = { maxBytes: 40_000_000, maxBatch: 20 }
const MB = (bytes: number) => `${Math.round((bytes / 1_000_000) * 10) / 10}MB`

type BatchRow = {
  name: string
  size: number
  status: '待读入' | '读入中' | '已读入' | '失败'
  detail: string
}

function ImportPanel({ onImported }: { onImported: () => void }) {
  const { active } = useProject()
  const [mode, setMode] = useState<'pdf' | 'text'>('pdf')
  const [files, setFiles] = useState<File[]>([])
  const [rows, setRows] = useState<BatchRow[]>([])
  const [limits, setLimits] = useState(DEFAULT_LIMITS)
  const [paperId, setPaperId] = useState('')
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [saveSource, setSaveSource] = useState(false)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const fileInput = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    let alive = true
    getSystemAccess()
      .then((access) => {
        if (!alive || !access.upload) return
        setLimits({
          maxBytes: access.upload.max_pdf_bytes,
          maxBatch: access.upload.max_batch_papers,
        })
      })
      .catch(() => undefined)
    return () => { alive = false }
  }, [])

  /** 选文件：超过篇数上限或单篇超大的直接说出来，不放进去等服务器报错。 */
  const pickFiles = (picked: File[]) => {
    if (picked.length === 0) return
    setError(null)
    setMessage(null)
    const tooBig = picked.filter((file) => file.size > limits.maxBytes)
    const usable = picked.filter((file) => file.size <= limits.maxBytes)
    if (usable.length > limits.maxBatch) {
      setError(`一次最多 ${limits.maxBatch} 篇，这次选了 ${usable.length} 篇。请分批导入。`)
      setFiles([])
      setRows([])
      return
    }
    const merged = [...files, ...usable].slice(0, limits.maxBatch)
    setFiles(merged)
    setRows(merged.map((file) => ({ name: file.name, size: file.size, status: '待读入', detail: '' })))
    if (tooBig.length > 0) {
      setError(
        `有 ${tooBig.length} 个文件超过单篇 ${MB(limits.maxBytes)} 上限，没有加进来：` +
          tooBig.map((file) => `${file.name}（${MB(file.size)}）`).join('、'),
      )
    }
  }

  const clearFiles = () => {
    setFiles([])
    setRows([])
    setError(null)
    setMessage(null)
    if (fileInput.current) fileInput.current.value = ''
  }

  const dropFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index))
    setRows((prev) => prev.filter((_, i) => i !== index))
    if (fileInput.current) fileInput.current.value = ''
  }

  const patchRow = (index: number, patch: Partial<BatchRow>) => {
    setRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)))
  }

  /** 只解析、不入库：走 /api/skills/pdf/extract，用来看这一篇 PDF 能不能读出来。 */
  const previewPdf = async () => {
    if (files.length !== 1) { setError('选一篇 PDF 再看解析结果。'); return }
    setPreviewing(true); setError(null)
    try {
      setPreview(await extractPdfTables(files[0], true))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setPreviewing(false)
    }
  }

  /** 撞到限流就等一会再发一次；批量导入时这条比报错有用。 */
  const ingestOne = async (file: File, index: number) => {
    const single = files.length === 1
    const payload = {
      file,
      profile_id: 'my-profile',
      paper_id: (single && paperId.trim()) || `upload-${Date.now()}-${index + 1}`,
      title: (single && title.trim()) || file.name.replace(/\.pdf$/i, ''),
      accept_threshold: 0.72,
      save_source: saveSource,
      project_id: active ? active.project_id : '',
    }
    try {
      return await ingestPdf(payload)
    } catch (err) {
      if (err instanceof ApiError && (err.status === 429 || err.status === 503)) {
        await new Promise((resolve) => setTimeout(resolve, 3000))
        return await ingestPdf(payload)
      }
      throw err
    }
  }

  const runPdf = async () => {
    if (!active) {
      setError('还没有选中的课题，先去「设置」建一个。')
      return
    }
    if (files.length === 0) {
      setError('先选 PDF 文件。')
      return
    }
    setBusy(true)
    setError(null)
    setMessage(null)
    let done = 0
    let failed = 0
    let relations = 0
    for (let index = 0; index < files.length; index += 1) {
      setProgress(`正在读入 ${index + 1}/${files.length}：${files[index].name}`)
      patchRow(index, { status: '读入中', detail: '' })
      try {
        const result = await ingestOne(files[index], index)
        relations += result.persistence?.project_candidate_count ?? result.summary?.candidate_relation_count ?? 0
        done += 1
        patchRow(index, { status: '已读入', detail: ingestLine(result) })
      } catch (err) {
        failed += 1
        patchRow(index, {
          status: '失败',
          detail: err instanceof Error ? err.message : String(err),
        })
      }
    }
    setProgress('')
    setBusy(false)
    setFiles([])
    setTitle('')
    setPaperId('')
    if (fileInput.current) fileInput.current.value = ''
    setMessage(
      `读入 ${done} 篇${failed > 0 ? `，${failed} 篇失败` : ''}；进课题合计 ${relations} 条。` +
        (failed > 0 ? '失败的那几篇按上面的原因改了再传。' : ''),
    )
    onImported()
  }

  const runText = async () => {
    if (!active) {
      setError('还没有选中的课题，先去「设置」建一个。')
      return
    }
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      if (text.trim().length < 20) throw new Error('粘贴的正文太短，至少要 20 个字。')
      const trimmedTitle = title.trim()
      const id = paperId.trim() || `upload-${Date.now()}`
      const result = await ingestPaper({
        paper_id: id,
        title: trimmedTitle || id,
        text,
        profile_id: 'my-profile',
        accept_threshold: 0.72,
        save_source: saveSource,
        project_id: active.project_id,
      })
      setMessage(`已读入：${ingestLine(result)}`)
      setText('')
      setTitle('')
      setPaperId('')
      onImported()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel">
      <div className="panel__body">
        <div className="toolbar" style={{ marginBottom: 12 }}>
          <button
            type="button"
            className={mode === 'pdf' ? 'btn btn--primary btn--sm' : 'btn btn--quiet btn--sm'}
            onClick={() => setMode('pdf')}
            aria-pressed={mode === 'pdf'}
          >
            上传 PDF
          </button>
          <button
            type="button"
            className={mode === 'text' ? 'btn btn--primary btn--sm' : 'btn btn--quiet btn--sm'}
            onClick={() => setMode('text')}
            aria-pressed={mode === 'text'}
          >
            粘贴正文
          </button>
          <span className="note">读入当前课题：{active?.name ?? '未选择课题'}</span>
        </div>

        <div className="toolbar" style={{ marginBottom: 12 }}>
          <label className="field">
            <span>论文标题</span>
            <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="留空就用文件名" />
          </label>
          <label className="field">
            <span>论文标识（可留空）</span>
            <input value={paperId} onChange={(event) => setPaperId(event.target.value)} placeholder="例如 zhang-2023-gnn" />
          </label>
        </div>

        {mode === 'pdf' ? (
          <>
            <label className="field">
              <span>PDF 文件（一次最多 {limits.maxBatch} 篇，单篇不超过 {MB(limits.maxBytes)}）</span>
              <input
                ref={fileInput}
                type="file"
                accept="application/pdf"
                multiple
                onChange={(event) => {
                  pickFiles(Array.from(event.target.files ?? []))
                  event.target.value = ''
                }}
              />
            </label>
            <p className="note" style={{ marginTop: 6 }}>
              可以一次选中多篇。选完点下面「读入」，系统会一篇一篇读，每篇的进度与结果都列在这里。
              标题与标识留空时用文件名；批量时不使用上面填的标题与标识。
            </p>
            {rows.length > 0 ? (
              <div className="list list--scroll" style={{ maxHeight: 260, marginTop: 8 }}>
                {rows.map((row, index) => (
                  <div className="list__row" key={`${row.name}-${index}`}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                      <strong>{row.name}</strong>
                      <span className="note">{MB(row.size)}</span>
                      <span
                        className="note"
                        style={{
                          color:
                            row.status === '失败'
                              ? 'var(--danger)'
                              : row.status === '已读入'
                                ? 'var(--supported)'
                                : undefined,
                        }}
                      >
                        {row.status}
                      </span>
                      {row.status === '待读入' && !busy ? (
                        <button
                          type="button"
                          className="btn btn--quiet btn--sm"
                          onClick={() => dropFile(index)}
                        >
                          移出
                        </button>
                      ) : null}
                    </div>
                    {row.detail ? <span className="note">{row.detail}</span> : null}
                  </div>
                ))}
              </div>
            ) : null}
          </>
        ) : (
          <label className="field">
            <span>正文</span>
            <textarea
              value={text}
              onChange={(event) => setText(event.target.value)}
              rows={5}
              placeholder="把论文正文粘进来。抽取会按段落切分并定位证据跨度。"
            />
          </label>
        )}

        <label className="check-inline" style={{ marginTop: 12 }}>
          <input
            type="checkbox"
            checked={saveSource}
            onChange={(event) => setSaveSource(event.target.checked)}
          />
          <span>允许把解析出的正文保存在本机数据库（默认不保存）</span>
        </label>

        {progress ? <p className="note" style={{ marginTop: 10 }}>{progress}</p> : null}
        {error ? <p className="note" style={{ color: 'var(--danger)', marginTop: 10 }}>{error}</p> : null}
        {message ? <p className="note" style={{ color: 'var(--supported)', marginTop: 10 }}>{message}</p> : null}

        {preview ? (
          <div style={{ marginTop: 12 }}>
            <SectionHead title="PDF 解析预览" hint="只解析，不入库" />
            <pre className="json-block">{JSON.stringify(preview, null, 2).slice(0, 2000)}</pre>
          </div>
        ) : null}
      </div>
      <div className="panel__foot" style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <button
          type="button"
          className="btn btn--primary"
          onClick={() => (mode === 'pdf' ? void runPdf() : void runText())}
          disabled={busy}
        >
          {busy
            ? (mode === 'pdf' ? progress || '正在读入…' : '正在读入…')
            : mode === 'pdf'
              ? `读入${files.length > 0 ? ` ${files.length} 篇` : '这个课题'}`
              : '读入这个课题'}
        </button>
        {mode === 'pdf' ? (
          <>
            <button
              type="button"
              className="btn btn--quiet btn--sm"
              onClick={previewPdf}
              disabled={previewing || files.length !== 1}
            >
              {previewing ? '解析中…' : '先看看能解析出什么'}
            </button>
            {files.length > 0 && !busy ? (
              <button type="button" className="btn btn--quiet btn--sm" onClick={clearFiles}>
                清空选择
              </button>
            ) : null}
          </>
        ) : null}
      </div>
    </div>
  )
}

/** 导入记录：本课题读过哪些论文、每次抽出了什么（读的是库里存下来的完整结果）。 */
function IngestionHistory({ refreshToken }: { refreshToken: number }) {
  const { active } = useProject()
  const [rows, setRows] = useState<IngestionSummaryRow[]>([])
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!active) { setRows([]); return }
    try {
      setRows(await getIngestions(50, active.project_id))
      setError(null)
    } catch (err) {
      setRows([])
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [active])

  useEffect(() => { void load() }, [load, refreshToken])

  if (!active) return null

  return (
    <div className="section">
      <SectionHead title="导入记录" hint={`共 ${rows.length} 次`} />
      {error ? <Empty title="读不到导入记录" body={error} danger /> : null}
      {rows.length === 0 ? (
        <Empty title="这个课题还没有导入记录" body="上面读入一篇论文之后，这里会出现它抽取出来的规模。" />
      ) : (
        <div className="list list--scroll" style={{ maxHeight: 280 }}>
          {rows.map((row) => (
            <button
              key={row.ingestion_id}
              type="button"
              className="list__row"
              onClick={async () => {
                try {
                  setDetail(await getIngestion(row.ingestion_id))
                } catch (err) {
                  setError(err instanceof Error ? err.message : String(err))
                }
              }}
            >
              <strong>{row.title || row.paper_id}</strong>
              <Meta
                items={[
                  row.source_kind,
                  row.created_at.slice(0, 19).replace('T', ' '),
                  row.source_saved ? '已保存原文' : '未保存原文',
                ]}
              />
            </button>
          ))}
        </div>
      )}
      {detail ? (
        <div className="panel" style={{ marginTop: 12 }}>
          <div className="panel__body">
            <SectionHead
              title="这次导入的抽取值"
              hint={String((detail as { ingestion_id?: string }).ingestion_id ?? '')}
            />
            <pre className="json-block">{JSON.stringify(detail.result ?? detail, null, 2).slice(0, 3000)}</pre>
          </div>
          <div className="panel__foot">
            <button type="button" className="btn btn--quiet btn--sm" onClick={() => setDetail(null)}>
              收起
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}



/** 文献库：读入自己的论文、看这个课题里有哪些论文、不想要的删掉。 */
export function LibraryPage() {
  const { active, refresh } = useProject()
  const [refreshToken, setRefreshToken] = useState(0)
  const bump = () => {
    void refresh()
    setRefreshToken((value) => value + 1)
  }

  return (
    <>
      <PageHead
        title="文献库"
        summary="读入自己的论文，导入后候选关系会进这个课题。"
      />

      <div className="section">
        <SectionHead title="读入自己的论文" hint={active ? `归到「${active.name}」` : '先选一个课题'} />
        <ImportPanel onImported={bump} />
      </div>

      <ProjectPaperList projectId={active?.project_id ?? ''} refreshToken={refreshToken} onDeleted={bump} />

      <IngestionHistory refreshToken={refreshToken} />
    </>
  )
}

/** 这个课题里的论文：一行一篇，不想要的直接删。
 *
 *  删除是**真删**：这篇论文的候选关系、证据引用与你的决定一起删掉，
 *  导入记录也清掉，返回删了几行，不写成一句"已删除"。 */
function ProjectPaperList({
  projectId,
  refreshToken,
  onDeleted,
}: {
  projectId: string
  refreshToken: number
  onDeleted: () => void
}) {
  const [papers, setPapers] = useState<ProjectPaper[]>([])
  const [relations, setRelations] = useState<Array<{ paper_id?: string; decision?: string | null }>>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<string | null>(null)
  const [busy, setBusy] = useState('')

  const load = useCallback(async () => {
    if (!projectId) {
      setPapers([])
      setRelations([])
      return
    }
    setLoading(true)
    try {
      const [rows, relationPayload] = await Promise.all([
        getProjectPapers(projectId),
        getProjectRelations(projectId),
      ])
      setPapers(Array.isArray(rows) ? rows : [])
      setRelations(relationPayload.relations ?? [])
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    void load()
  }, [load, refreshToken])

  const countsByPaper = useMemo(() => {
    const tally: Record<string, { total: number; included: number }> = {}
    for (const relation of relations) {
      const key = String(relation.paper_id ?? '')
      if (!key) continue
      const entry = tally[key] ?? { total: 0, included: 0 }
      entry.total += 1
      if (relation.decision === 'include') entry.included += 1
      tally[key] = entry
    }
    return tally
  }, [relations])

  const remove = async (paper: ProjectPaper) => {
    setBusy(paper.paper_id)
    setNotice(null)
    setError(null)
    try {
      const outcome = await removeProjectPaper(projectId, paper.paper_id)
      const rows = outcome.rows ?? {}
      setNotice(
        `已删除《${outcome.title}》：候选关系 ${rows.relations ?? 0} 条、` +
          `证据片段 ${(rows.evidence ?? 0) + (rows.stray_evidence ?? 0)} 条、` +
          `你的决定 ${rows.decisions ?? 0} 条、导入记录 ${rows.ingestions ?? 0} 条。`,
      )
      setConfirming(null)
      await load()
      onDeleted()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="section">
      <SectionHead title="这个课题的论文" hint={`${papers.length} 篇`} />
      {error ? <Empty title="读取失败" body={error} danger /> : null}
      {notice ? <p className="note" style={{ color: 'var(--supported)' }}>{notice}</p> : null}
      {papers.length === 0 && !loading ? (
        <Empty title="还没有论文" body="在上面读入一篇，导入后候选关系会进这个课题。" />
      ) : (
        <ul className="list">
          {papers.map((paper) => {
            const counts = countsByPaper[paper.paper_id] ?? { total: 0, included: 0 }
            return (
              <li key={paper.paper_id} className="list__row" style={{ cursor: 'default' }}>
                <div style={{ minWidth: 0 }}>
                  <strong>{paper.title}</strong>
                  <Meta
                    items={[
                      paper.source_kind === 'knowledge_db' ? '从全文知识库接入' : '自己读入',
                      `候选关系 ${counts.total} 条`,
                      `已纳入 ${counts.included} 条`,
                    ]}
                  />
                </div>
                {confirming === paper.paper_id ? (
                  <span className="toolbar" style={{ marginBottom: 0 }}>
                    <button
                      type="button"
                      className="btn btn--primary btn--sm"
                      disabled={busy !== ''}
                      onClick={() => void remove(paper)}
                    >
                      {busy === paper.paper_id ? '删除中…' : '确认删除'}
                    </button>
                    <button
                      type="button"
                      className="btn btn--quiet btn--sm"
                      onClick={() => setConfirming(null)}
                    >
                      先不删
                    </button>
                  </span>
                ) : (
                  <button
                    type="button"
                    className="btn btn--quiet btn--sm"
                    onClick={() => {
                      setNotice(null)
                      setConfirming(paper.paper_id)
                    }}
                  >
                    删除
                  </button>
                )}
              </li>
            )
          })}
        </ul>
      )}
      {confirming ? (
        <p className="note">删除会连同这篇论文的候选关系、证据片段与你的决定一起删掉，删了不能恢复。</p>
      ) : null}
    </div>
  )
}
