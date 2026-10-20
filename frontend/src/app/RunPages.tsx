import { useEffect, useMemo, useState } from 'react'
import {
  adoptRunClaims,
  decideRelation,
  getHistory,
  getHistoryDetail,
  getProfiles,
  getProjectPapers,
  getProviders,
  runPipeline,
  sendFeedback,
  streamPipeline,
  testProvider,
} from '../api'
import type { AgentTraceStep, ResearchProgressEvent, RunResult } from '../types'
import { DomainSelect, useDomains } from './domains'
import { PaperMatrix } from './PaperMatrix'
import { useProject } from './project'
import { Empty, Meta, PageHead, SectionHead, StatusTag, Toast } from './ui'

/** 一条主张怎么展示：有现成的句子就用，没有就用「实体 —关系→ 实体」拼出来。
 *
 *  后端的主张只有 source / relation / target 三个字段，没有整句；
 *  以前这里退回「主张 N」，等于把内容藏起来了。 */
function claimLabel(item: Record<string, unknown>, index: number): string {
  const existing = pick(item, ['text', 'statement', 'claim', 'summary'])
  if (existing) return existing
  const source = pick(item, ['source'])
  const target = pick(item, ['target'])
  if (!source && !target) return `主张 ${index + 1}`
  const relationType = pick(item, ['relation_type', 'relation']) || '关联'
  return `${source} —${relationType}→ ${target}`
}

/** 这次运行用了谁的证据：自己的论文几篇、公共语料几篇，列清楚。
 *
 *  不写这一段的话，用户没法判断一条结论到底是"从我的文献里来的"还是"从公共语料里来的"。
 *  库有上千篇时还要写清"这次按问题挑了几篇"——两个数分开说，别让人以为整库都分析了。 */
function EvidenceScope({ scope }: { scope?: Record<string, unknown> | null }) {
  if (!scope) return null
  const projectCount = Number(scope.project_paper_count ?? 0)
  const corpusIncluded = scope.corpus_included !== false
  const corpusCount = Number(scope.corpus_paper_count ?? 0)
  const libraryCount = Number(scope.project_library_paper_count ?? 0)
  const selection = String(scope.project_selection ?? '')
  const titles = Array.isArray(scope.project_papers)
    ? (scope.project_papers as Array<Record<string, unknown>>)
        .map((item) => String(item.title ?? item.paper_id ?? ''))
        .filter(Boolean)
    : []
  const selectionNote =
    libraryCount > projectCount
      ? selection === 'query'
        ? `从课题库的 ${libraryCount} 篇里按这次的研究问题挑了 ${projectCount} 篇`
        : `从课题库的 ${libraryCount} 篇里取了最近加入的 ${projectCount} 篇`
      : null
  return (
    <div className="panel" style={{ marginBottom: 16 }}>
      <div className="panel__body">
        <div className="toolbar" style={{ marginBottom: 6 }}>
          <span className="note">这次运行的证据来源：</span>
          <span className="tag tag--plain">你导入的论文 {projectCount} 篇</span>
          <span className="tag tag--plain">
            {corpusIncluded ? `公共语料 ${corpusCount} 篇` : '没用公共语料'}
          </span>
        </div>
        {selectionNote ? <p className="note" style={{ margin: 0, marginBottom: 4 }}>{selectionNote}。</p> : null}
        {titles.length > 0 ? (
          <p className="note" style={{ margin: 0 }}>
            用到的是：{titles.slice(0, 6).join('；')}
            {titles.length > 6 ? ` 等 ${titles.length} 篇` : ''}
          </p>
        ) : (
          <p className="note" style={{ margin: 0 }}>
            当前课题还没有论文。
          </p>
        )}
      </div>
    </div>
  )
}

/** 一条主张的证据是谁的：自己导入的论文 / 公共语料 / 两边都有。 */
const ORIGIN_LABEL: Record<string, string> = {
  project: '证据来自你导入的论文',
  corpus: '证据来自公共语料',
  mixed: '证据两边都有',
  none: '没有证据',
}

/** 从后端返回的任意对象里取一个可读字符串，取不到就给空字符串——不猜字段语义。 */
function pick(source: unknown, keys: string[]): string {
  if (!source || typeof source !== 'object') return ''
  const record = source as Record<string, unknown>
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'string' && value.trim()) return value
    if (typeof value === 'number') return String(value)
  }
  return ''
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

/** 研究工作台：提问 → 实时进度 → 主张与证据 → 反馈 → 历史回看。
 *
 *  运行走 `/api/run/stream`（SSE），页面上每个百分比都来自后端事件；
 *  流式不可用时退回同步 `/api/run`，并在页面上写明这次是退回来的。 */
export function ResearchPage() {
  const { active, refresh } = useProject()
  const [query, setQuery] = useState('')
  const domainState = useDomains()
  const domainId = domainState.domainId
  const [profileId, setProfileId] = useState('')
  const [providerId, setProviderId] = useState('')
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [advanced, setAdvanced] = useState(false)
  const [profiles, setProfiles] = useState<Array<{ id: string; name: string }>>([])
  const [providers, setProviders] = useState<Array<{ id: string; label: string; model?: string }>>([])
  const [result, setResult] = useState<RunResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [selectedClaim, setSelectedClaim] = useState(0)
  const [progress, setProgress] = useState<ResearchProgressEvent | null>(null)
  const [steps, setSteps] = useState<AgentTraceStep[]>([])
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<string | null>(null)
  const [feedbackBusy, setFeedbackBusy] = useState(false)
  const [history, setHistory] = useState<Array<Record<string, unknown>>>([])
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null)
  const [adopting, setAdopting] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [projectPaperCount, setProjectPaperCount] = useState<number | null>(null)

  const projectId = active?.project_id ?? ''

  useEffect(() => {
    getProfiles()
      .then((items) => {
        // 下拉框要存 profile_id，不是画像名字：/api/run 按 id 找人，
        // 传名字会被判成"画像不存在或不属于当前用户"（以前就是这么错的）。
        setProfiles(items.map((item) => ({
          id: String(item.profile_id ?? ''),
          name: String(item.name ?? ''),
        })))
        setProfileId((current) => current || String(items[0]?.profile_id ?? ''))
      })
      .catch(() => setProfiles([]))
    getProviders()
      .then((payload) => {
        const list = payload.providers ?? []
        setProviders(list.map((item) => ({
          id: String(item.id ?? ''),
          label: String(item.label ?? item.id ?? ''),
          model: String(item.default_model ?? ''),
        })))
        setProviderId((current) => current || String(list[0]?.id ?? 'mock'))
      })
      .catch(() => setProviders([]))
  }, [])

  const loadHistory = () => {
    getHistory(20, projectId || undefined)
      .then(setHistory)
      .catch(() => setHistory([]))
  }

  useEffect(loadHistory, [projectId])

  // 当前课题里到底有几篇自己导入的论文：决定这次能不能跑、以及页面上怎么提示。
  useEffect(() => {
    if (!projectId) { setProjectPaperCount(null); return }
    getProjectPapers(projectId)
      .then((rows) => setProjectPaperCount(Array.isArray(rows) ? rows.length : 0))
      .catch(() => setProjectPaperCount(null))
  }, [projectId])

  const currentProvider = providers.find((item) => item.id === providerId)

  const buildPayload = () => ({
    profile_id: profileId,
    query,
    domain_id: domainId || undefined,
    project_id: projectId || undefined,
    // 默认把自己导入的论文算进来；界面上可以关掉，也可以选择不要公共语料。
    use_project_papers: true,
    include_corpus: false,
    llm: {
      provider: providerId || 'mock',
      model: model || currentProvider?.model || '',
      api_key: apiKey || undefined,
    },
  })

  const start = async () => {
    if (!query.trim()) { setError('先写一句研究问题。'); return }
    setLoading(true); setError(null); setNotice(null)
    setResult(null); setProgress(null); setSteps([])
    const payload = buildPayload()
    try {
      const response = await streamPipeline(payload, {
        onProgress: (event) => setProgress(event),
        onStep: (step) => setSteps((current) => [...current, step]),
      })
      setResult(response)
      setSelectedClaim(0)
    } catch (streamError) {
      // 流式不可用时退回同步接口，并在页面上说清楚这次是退回来的。
      try {
        const response = await runPipeline(payload)
        setResult(response)
        setSelectedClaim(0)
        setNotice(
          `实时进度不可用（${streamError instanceof Error ? streamError.message : String(streamError)}），` +
            '这次是同步跑完的，过程按事后记录显示。',
        )
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
      }
    } finally {
      setLoading(false)
      loadHistory()
    }
  }

  const testConnection = async () => {
    setTesting(true); setTestResult(null)
    try {
      const outcome = await testProvider({
        provider: providerId || 'mock',
        model: model || currentProvider?.model || '',
        api_key: apiKey || undefined,
      })
      setTestResult(
        outcome.ok
          ? `连通正常（${outcome.provider}${outcome.model ? ' / ' + outcome.model : ''}` +
              `${outcome.duration_ms ? '，' + Math.round(outcome.duration_ms) + 'ms' : ''}）`
          : `连不上：${outcome.message || '未返回原因'}`,
      )
    } catch (err) {
      setTestResult(err instanceof Error ? err.message : String(err))
    } finally {
      setTesting(false)
    }
  }

  const sendDifficulty = async (value: 'too_hard' | 'suitable' | 'too_easy') => {
    setFeedbackBusy(true); setError(null)
    try {
      const response = await sendFeedback({
        profile_id: profileId,
        query,
        domain_id: domainId || undefined,
        feedback: value,
      })
      setResult(response)
      setNotice('已按你的反馈重跑一次，画像难度已调整。')
      loadHistory()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setFeedbackBusy(false)
    }
  }

  const openHistory = async (id: string) => {
    try {
      setDetail(await getHistoryDetail(id))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const claims = useMemo(() => asArray(result?.claims), [result])
  const trace = useMemo(() => asArray(result?.agent_trace), [result])
  const resources = useMemo(() => asArray(result?.resources), [result])
  const current = claims[selectedClaim] as Record<string, unknown> | undefined

  /** 把这条主张收进课题；asInclude 时顺手直接决定「加入我的图谱」。 */
  const adoptClaim = async (mode: 'candidate' | 'include') => {
    if (!active || !current) return
    setAdopting(true)
    setError(null)
    try {
      const evidenceIds = asArray(current.evidence_ids).map(String)
      const allSpans = Object.values(result?.evidence_details ?? {}).flat()
      const evidence = allSpans.filter((span) => evidenceIds.includes(span.evidence_id))
      const claim = {
        claim_id: pick(current, ['claim_id', 'id']) || String(selectedClaim),
        source: pick(current, ['source']),
        target: pick(current, ['target']),
        relation_type: pick(current, ['relation_type', 'relation']),
        status: pick(current, ['status', 'verdict']) || 'needs_review',
        judge_score: Number(pick(current, ['judge_score']) || 0),
        evidence,
      }
      const outcome = await adoptRunClaims(active.project_id, {
        run_id: pick(result, ['run_id']) || 'run',
        claims: [claim],
      })
      if (mode === 'include' && outcome.candidates_total > 0) {
        await decideRelation(
          active.project_id,
          `run:${pick(result, ['run_id']) || 'run'}:${claim.claim_id}`,
          'include',
          '来自研究工作台的主张',
        )
      }
      setToast(
        mode === 'include'
          ? '已纳入我的图谱。'
          : '已存进课题，去「构建图谱」可以逐条审。',
      )
      if (mode === 'include') {
        // 让侧栏与图谱计数刷新
        await refresh()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setAdopting(false)
    }
  }

  return (
    <>
      <PageHead
        title="研究工作台"
        summary="提一个研究问题，看系统找到哪些文献、形成哪些主张、各自靠什么证据。"
      />

      <div className="panel" style={{ marginBottom: 20 }}>
        <div className="panel__body">
          <label className="field">
            <span>研究问题</span>
            <textarea
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              rows={3}
              placeholder="例如：图神经网络在材料性质预测里依赖哪些数据集？这些关系有哪些原文支持？"
            />
          </label>
          <div className="toolbar" style={{ marginTop: 12, marginBottom: 0 }}>
            <DomainSelect state={domainState} />
            <label className="field">
              <span>学习者画像</span>
              <select value={profileId} onChange={(event) => setProfileId(event.target.value)}>
                {profiles.map((profile) => (
                  <option key={profile.id} value={profile.id}>{profile.name}</option>
                ))}
              </select>
            </label>
            <button type="button" className="btn btn--quiet btn--sm" onClick={() => setAdvanced((value) => !value)}>
              {advanced ? '收起高级设置' : '高级设置'}
            </button>
            <span style={{ flex: 1 }} />
            <button type="button" className="btn btn--primary" onClick={start} disabled={loading}>
              {loading ? '分析中…' : '开始分析'}
            </button>
          </div>
          {projectPaperCount === 0 ? (
            <p className="note" style={{ marginTop: 8 }}>
              这个课题还没有论文。先去「文献库」读入论文，再回来分析。
            </p>
          ) : null}

          {advanced ? (
            <>
              <div className="toolbar" style={{ marginTop: 12, marginBottom: 0 }}>
                <label className="field">
                  <span>分析方式</span>
                  <select value={providerId} onChange={(event) => setProviderId(event.target.value)}>
                    {providers.map((provider) => (
                      <option key={provider.id} value={provider.id}>{provider.label}</option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>模型</span>
                  <input value={model} onChange={(event) => setModel(event.target.value)} placeholder={currentProvider?.model || '默认'} />
                </label>
                <label className="field field--grow">
                  <span>接口密钥（只参与本次请求，不保存）</span>
                  <input value={apiKey} onChange={(event) => setApiKey(event.target.value)} type="password" autoComplete="off" />
                </label>
                <button type="button" className="btn btn--quiet btn--sm" onClick={testConnection} disabled={testing}>
                  {testing ? '测试中…' : '测试连接'}
                </button>
              </div>
              {testResult ? <p className="note" style={{ marginTop: 8 }}>{testResult}</p> : null}
            </>
          ) : null}
        </div>
      </div>

      {error ? <Empty title="这次没有跑完" body={error} danger /> : null}
      {notice ? <p className="note" style={{ marginBottom: 12 }}>{notice}</p> : null}
      {toast ? <Toast text={toast} onDone={() => setToast(null)} /> : null}

      <PaperMatrix />

      {loading && progress ? (
        <div className="panel" style={{ marginBottom: 20 }}>
          <div className="panel__body">
            <div className="toolbar" style={{ marginBottom: 8 }}>
              <strong style={{ fontSize: 14 }}>{progress.title}</strong>
              <span className="note">{progress.percent}% · {progress.phase}</span>
            </div>
            <div
              className="progress"
              role="progressbar"
              aria-valuenow={progress.percent}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <span style={{ width: `${Math.min(100, Math.max(0, progress.percent))}%` }} />
            </div>
            <p className="note" style={{ marginTop: 8 }}>{progress.message}</p>
            {steps.length > 0 ? (
              <ul className="checklist" style={{ marginTop: 12 }}>
                {steps.slice(-6).map((step, index) => (
                  <li key={`${step.agent}-${index}`}>
                    <i>{index + 1}</i>
                    <span>{step.role || step.agent} · {step.status}{step.summary ? ` — ${step.summary}` : ''}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        </div>
      ) : null}

      {result ? (
        <>
          <EvidenceScope scope={result.evidence_scope} />
          <div className="toolbar">
            <span className="note">这次结果</span>
            {([
              ['too_hard', '太难了'],
              ['suitable', '合适'],
              ['too_easy', '太简单'],
            ] as Array<['too_hard' | 'suitable' | 'too_easy', string]>).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className="btn btn--quiet btn--sm"
                onClick={() => void sendDifficulty(value)}
                disabled={feedbackBusy}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="three-pane">
            <div className="pane">
              <div className="pane__head">找到的文献 {resources.length ? `· ${resources.length}` : ''}</div>
              <div className="pane__body" style={{ padding: 0 }}>
                {resources.length === 0 ? (
                  <div style={{ padding: 14 }}>
                    <Empty title="没有检索到文献" body="当前检索范围内没有结果。可以换领域、换问题，或先把论文导入文献库。" />
                  </div>
                ) : (
                  resources.map((resource, index) => {
                    const item = resource as Record<string, unknown>
                    return (
                      <div className="list__row" key={index}>
                        <strong>{pick(item, ['title', 'name', 'paper_title']) || '未命名文献'}</strong>
                        <Meta items={[pick(item, ['venue', 'source']), pick(item, ['year']), pick(item, ['tier', 'evidence_tier'])]} />
                      </div>
                    )
                  })
                )}
              </div>
            </div>

            <div className="pane">
              <div className="pane__head">主张与判断 · 共 {claims.length} 条</div>              <div className="pane__body">
                {claims.length === 0 ? (
                  <Empty title="这次没有形成主张" body="分析已经结束，但没有从检索到的文献里得到可陈述的主张。这不是成功，也不是失败：换一个问题或换更大的检索范围再试。" />
                ) : (
                  claims.map((claim, index) => {
                    const item = claim as Record<string, unknown>
                    const status = pick(item, ['status', 'verdict']) || 'unknown'
                    const origin = ORIGIN_LABEL[String(item.evidence_origin ?? '')]
                    return (
                      <button
                        key={index}
                        type="button"
                        className={`list__row${index === selectedClaim ? ' is-active' : ''}`}
                        onClick={() => setSelectedClaim(index)}
                      >
                        <strong>{claimLabel(item, index)}</strong>
                        <Meta items={[status, ...(origin ? [origin] : [])]} />
                      </button>
                    )
                  })
                )}
                {current ? (
                  <div className="panel">
                    <div className="panel__body">
                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
                        <StatusTag status={pick(current, ['status', 'verdict']) || 'unknown'} />
                        <span className="tag tag--plain">机器判断，未人工核验</span>
                        {ORIGIN_LABEL[String(current.evidence_origin ?? '')] ? (
                          <span className="tag tag--plain">{ORIGIN_LABEL[String(current.evidence_origin)]}</span>
                        ) : null}
                      </div>
                      <p className="quote">{claimLabel(current, selectedClaim)}</p>
                      <p className="note" style={{ marginTop: 8 }}>
                        证据条数：
                        {asArray(current.evidence_ids).length || asArray(current.evidence).length || pick(current, ['evidence_count']) || '—'}
                      </p>
                    </div>
                    <div className="panel__foot" style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                      <button
                        type="button"
                        className="btn btn--quiet btn--sm"
                        onClick={() => void adoptClaim('candidate')}
                        disabled={!active || adopting}
                      >
                        {adopting ? '正在写入…' : '存进课题'}
                      </button>
                      <button
                        type="button"
                        className="btn btn--primary btn--sm"
                        onClick={() => void adoptClaim('include')}
                        disabled={!active || adopting}
                      >
                        纳入我的图谱
                      </button>
                    </div>
                  </div>
                ) : null}
              </div>
            </div>

            <div className="pane">
              <div className="pane__head">分析过程</div>
              <div className="pane__body">
                {trace.length === 0 ? (
                  <Empty title="没有过程记录" body="本次运行没有返回可展示的步骤。" />
                ) : (
                  <ul className="checklist">
                    {trace.map((step, index) => {
                      const item = step as Record<string, unknown>
                      return (
                        <li key={index}>
                          <i>{index + 1}</i>
                          <span>
                            {pick(item, ['role', 'agent', 'name']) || '步骤'}
                            {pick(item, ['status']) ? ` · ${pick(item, ['status'])}` : ''}
                            {pick(item, ['message', 'detail', 'summary']) ? ` — ${pick(item, ['message', 'detail', 'summary'])}` : ''}
                          </span>
                        </li>
                      )
                    })}
                  </ul>
                )}
                <dl className="kv" style={{ marginTop: 12 }}>
                  <dt>运行编号</dt>
                  <dd className="mono">{pick(result, ['run_id']) || '—'}</dd>
                  <dt>分析方式</dt>
                  <dd>{currentProvider?.label ?? providerId}</dd>
                </dl>
              </div>
            </div>
          </div>
        </>
      ) : null}

      <div className="section" style={{ marginTop: 24 }}>
        <SectionHead title="本课题运行历史" hint={`共 ${history.length} 次`} />
        {history.length === 0 ? (
          <Empty title="还没有运行记录" body="这个课题还没跑过研究任务。上面提一个问题就会有记录。" />
        ) : (
          <div className="list list--scroll" style={{ maxHeight: 300 }}>
            {history.map((row) => {
              const id = String(row.research_session_id ?? '')
              return (
                <button key={id} type="button" className="list__row" onClick={() => void openHistory(id)}>
                  <strong>{String(row.query ?? '(没有问题文本)')}</strong>
                  <Meta
                    items={[
                      String(row.domain_label ?? ''),
                      String(row.created_at ?? '').slice(0, 19).replace('T', ' '),
                      `${row.paper_count ?? 0} 篇文献`,
                    ]}
                  />
                </button>
              )
            })}
          </div>
        )}
        {detail ? (
          <div className="panel" style={{ marginTop: 12 }}>
            <div className="panel__body">
              <SectionHead title="这次运行的完整记录" hint={String(detail.research_session_id ?? '')} />
              <pre className="json-block">
                {JSON.stringify(detail, null, 2).slice(0, 4000)}
              </pre>
            </div>
            <div className="panel__foot">
              <button type="button" className="btn btn--quiet btn--sm" onClick={() => setDetail(null)}>
                收起
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </>
  )
}
