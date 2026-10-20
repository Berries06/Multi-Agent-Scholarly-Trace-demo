import { useCallback, useEffect, useState } from 'react'
import {
  addProjectLead,
  addProjectMember,
  archiveProject,
  clearProjectSources,
  deleteProjectLead,
  deleteProject,
  diagnoseText,
  diffProjectVersions,
  downloadProjectCsv,
  downloadProjectExport,
  getAuthStatus,
  getHistory,
  getMyProfile,
  getProjectGraph,
  getProjectGraphVersions,
  getProjectLeads,
  getProjectMembers,
  getProjects,
  getProviders,
  getReadiness,
  getSkills,
  getSystemAccess,
  humanizeText,
  modelChat,
  removeProjectMember,
  runResearchSkill,
  snapshotProjectGraph,
  updateProject,
} from '../api'
import type {
  AuthStatus,
  DiagnoseReport,
  HumanizeReport,
  LearnerProfile,
  ProjectGraph,
  ProjectGraphVersion,
  ReadinessReport,
  SkillEntry,
  SystemAccess,
} from '../types'
import type { ProjectLead, ProjectMember, VersionDiff } from '../api'
import { CorpusNote, DomainSelect, useDomains } from './domains'
import { useProject } from './project'
import { Empty, PageHead, SectionHead } from './ui'

function useProjectGraphData() {
  const { active } = useProject()
  const [graph, setGraph] = useState<ProjectGraph | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    if (!active) {
      setGraph(null)
      return
    }
    setLoading(true)
    try {
      const result = await getProjectGraph(active.project_id)
      setGraph(result)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [active])

  useEffect(() => {
    void load()
  }, [load])

  return { graph, error, loading, reload: load }
}

/** 课题概览：这个课题现在有什么、下一步该做什么。 */
export function ProjectOverviewPage({ onNavigate }: { onNavigate: (section: string) => void }) {
  const { active, projects } = useProject()
  const { graph, error, loading } = useProjectGraphData()
  const [runs, setRuns] = useState<number | null>(null)

  useEffect(() => {
    if (!active) return
    let alive = true
    getHistory(50, active.project_id)
      .then((rows) => { if (alive) setRuns(rows.length) })
      .catch(() => { if (alive) setRuns(null) })
    return () => { alive = false }
  }, [active])

  if (!active) {
    return (
      <>
        <PageHead title="课题概览" summary="每个研究课题都有自己的论文、候选关系与图谱。" />
        <Empty
          title="还没有研究课题"
          body="去「设置」新建一个，或者等默认课题创建完成后再刷新。"
        />
      </>
    )
  }

  const counts = graph?.counts
  const show = (value: number | undefined) => (counts ? String(value ?? 0) : '—')

  return (
    <>
      <PageHead
        title={active.name}
        summary={active.description || '在「设置」里写一句这个课题要回答什么。'}
        actions={
          <button type="button" className="btn btn--primary" onClick={() => onNavigate('workbench')}>
            开始一次研究
          </button>
        }
      />

      {error ? <Empty title="取数失败" body={error} danger /> : null}

      <div className="stats" role="list">
        <div>
          <dt>已纳入关系</dt>
          <dd className="num">{show(counts?.included)}</dd>
        </div>
        <div>
          <dt>待你决定</dt>
          <dd className="num">{show(counts?.undecided)}</dd>
        </div>
        <div>
          <dt>暂缓 / 排除</dt>
          <dd className="num">{counts ? `${counts.defer} / ${counts.exclude}` : '—'}</dd>
        </div>
        <div>
          <dt>研究次数</dt>
          <dd className="num">{runs === null ? '—' : runs}</dd>
        </div>
      </div>

      <div className="grid-2" style={{ marginTop: 24 }}>
        <div>
          <SectionHead title="下一步" hint={loading ? '读取中…' : undefined} />
          <div className="panel">
            <div className="panel__body">
              <ul className="checklist">
                {(counts?.relations ?? 0) === 0 ? (
                  <li><i>1</i><span>先去「文献库」读入论文，抽出来的候选关系会进「构建图谱」。</span></li>
                ) : (counts?.undecided ?? 0) > 0 ? (
                  <li><i>1</i><span>还有 {counts?.undecided} 条候选没审，去「构建图谱」读原文再决定。</span></li>
                ) : (
                  <li><i>1</i><span>候选都审完了，去「知识图谱」看形状，或者去「设置」导出。</span></li>
                )}
                <li><i>2</i><span>在工作台提问，主张与证据会一起返回，可以回「证据中心」逐条核。</span></li>
                <li><i>3</i><span>「研究发现」汇总这个课题里你纳入的关系。</span></li>
              </ul>
            </div>
            <div className="panel__foot">
              <button type="button" className="btn btn--quiet btn--sm" onClick={() => onNavigate('build')}>
                打开构建图谱 →
              </button>
            </div>
          </div>
        </div>
        <div>
          <SectionHead title="课题一览" hint={`共 ${projects.length} 个`} />
          <div className="list">
            {projects.map((project) => (
              <div className="list__row" key={project.project_id} style={{ cursor: 'default' }}>
                <strong>{project.name}</strong>
                <span className="list__meta">
                  <span>论文 {project.paper_count ?? 0}</span>
                  <span>候选 {project.relation_count ?? 0}</span>
                  <span>已加入 {project.included_count ?? 0}</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}

/** 研究发现：把已纳入的关系和语料线索放在一起看，也能分开看。 */
export function FindingsPage({ onNavigate }: { onNavigate: (section: string) => void }) {
  const { active } = useProject()
  const { graph, error } = useProjectGraphData()
  const [view, setView] = useState<'merged' | 'relations' | 'leads'>('merged')
  const [leads, setLeads] = useState<ProjectLead[]>([])
  const [leadsToken, setLeadsToken] = useState(0)

  const projectId = active?.project_id ?? ''

  useEffect(() => {
    if (!projectId) { setLeads([]); return }
    let alive = true
    getProjectLeads(projectId)
      .then((payload) => { if (alive) setLeads(payload.leads ?? []) })
      .catch(() => { if (alive) setLeads([]) })
    return () => { alive = false }
  }, [projectId, leadsToken])

  if (!active) {
    return (
      <>
        <PageHead title="研究发现" summary="汇总本课题里你自己的判断与依据。" />
        <Empty title="还没有选中的课题" body="先去「设置」新建一个课题。" />
      </>
    )
  }

  const edges = graph?.edges ?? []
  const byPaper = new Map<string, typeof edges>()
  for (const edge of edges) {
    const key = edge.paper_id || '未标来源'
    byPaper.set(key, [...(byPaper.get(key) ?? []), edge])
  }

  // 合并视图：关系按决定时间、线索按记录时间，混在一起按时间倒序
  const merged = [
    ...edges.map((edge) => ({
      kind: 'relation' as const,
      key: edge.relation_id,
      title: `${edge.source_name} —${edge.relation_type}→ ${edge.target_name}`,
      meta: [
        edge.paper_id,
        edge.decision ? `你的决定：${edge.decision}` : '未决定',
        edge.evidence_count ? `${edge.evidence_count} 条证据` : '无证据片段',
      ],
      time: String(edge.decided_at ?? ''),
    })),
    ...leads.map((lead) => ({
      kind: 'lead' as const,
      key: lead.lead_id,
      title: lead.title,
      meta: [lead.source_kind, lead.detail].filter(Boolean) as string[],
      time: lead.created_at,
    })),
  ].sort((left, right) => (left.time < right.time ? 1 : -1))

  return (
    <>
      <PageHead title="研究发现" summary="已纳入的关系与语料线索。" />

      {error ? <Empty title="取数失败" body={error} danger /> : null}

      <LeadsPanel onChanged={() => setLeadsToken((value) => value + 1)} />

      <div className="toolbar">
        {([
          ['merged', `合并 ${edges.length + leads.length}`],
          ['relations', `关系 ${edges.length}`],
          ['leads', `线索 ${leads.length}`],
        ] as Array<['merged' | 'relations' | 'leads', string]>).map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={view === key ? 'btn btn--primary btn--sm' : 'btn btn--quiet btn--sm'}
            onClick={() => setView(key)}
            aria-pressed={view === key}
          >
            {label}
          </button>
        ))}
        <span style={{ flex: 1 }} />
        <button type="button" className="btn btn--quiet btn--sm" onClick={() => onNavigate('settings')}>
          去设置导出 →
        </button>
      </div>

      {view === 'merged' ? (
        merged.length === 0 ? (
          <Empty title="还没有内容" body="去「构建图谱」纳入关系，或在上面记一条线索。" />
        ) : (
          <div className="list">
            {merged.map((row) => (
              <div className="list__row" key={`${row.kind}-${row.key}`} style={{ cursor: 'default' }}>
                <strong>
                  <span className={row.kind === 'relation' ? 'tag tag--accepted' : 'tag tag--review'}>
                    {row.kind === 'relation' ? '关系' : '线索'}
                  </span>{' '}
                  {row.title}
                </strong>
                <span className="list__meta">
                  {row.meta.map((item) => <span key={item}>{item}</span>)}
                  <span>{row.time.slice(0, 16).replace('T', ' ')}</span>
                </span>
              </div>
            ))}
          </div>
        )
      ) : view === 'relations' ? (
        edges.length === 0 ? (
          <Empty
            title="还没有已纳入的关系"
            body="先去「构建图谱」做决定，或者去「文献库」读入论文。"
          />
        ) : (
          Array.from(byPaper.entries()).map(([paperId, rows]) => (
            <div className="section" key={paperId}>
              <SectionHead title={paperId} hint={`${rows.length} 条关系`} />
              <div className="list">
                {rows.map((edge) => (
                  <div className="list__row" key={edge.relation_id} style={{ cursor: 'default' }}>
                    <strong>{edge.source_name} —{edge.relation_type}→ {edge.target_name}</strong>
                    <span className="list__meta">
                      <span>机器状态：{edge.machine_status}</span>
                      <span>你的决定：{edge.decision ?? '未决定'}</span>
                      <span>
                        {edge.evidence_count > 0 ? `${edge.evidence_count} 条证据片段` : '没有证据片段'}
                      </span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))
        )
      ) : leads.length === 0 ? (
        <Empty title="还没有线索" body="在上面输入框记一条，或者在「知识图谱」的语料侧工具里把发现记下来。" />
      ) : (
        <div className="list">
          {leads.map((lead) => (
            <div className="list__row" key={lead.lead_id} style={{ cursor: 'default' }}>
              <strong>{lead.title}</strong>
              <span className="list__meta">
                <span>{lead.source_kind}</span>
                {lead.detail ? <span>{lead.detail}</span> : null}
                <span>{lead.created_at.slice(0, 16).replace('T', ' ')}</span>
              </span>
            </div>
          ))}
        </div>
      )}

      <WritingSkillsPanel />
    </>
  )
}

/** 课题共享：属主把课题给别的账号看或一起改。
 *
 *  editor 能改，viewer 只能看；分享与取消分享只有属主能做（后端也按这个拦）。 */
function SharePanel() {
  const { active, refresh } = useProject()
  const [owner, setOwner] = useState<ProjectMember | null>(null)
  const [members, setMembers] = useState<ProjectMember[]>([])
  const [myRole, setMyRole] = useState('owner')
  const [account, setAccount] = useState('')
  const [role, setRole] = useState<'editor' | 'viewer'>('editor')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const projectId = active?.project_id ?? ''

  const load = useCallback(async () => {
    if (!projectId) return
    try {
      const payload = await getProjectMembers(projectId)
      setOwner(payload.owner)
      setMembers(payload.members ?? [])
      setMyRole(payload.my_role)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [projectId])

  useEffect(() => { void load() }, [load])

  const share = async () => {
    if (!projectId || !account.trim()) return
    setBusy(true)
    try {
      await addProjectMember(projectId, account.trim(), role)
      setAccount('')
      await load()
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  if (!active) return null

  return (
    <div className="section">
      <SectionHead title="共享" hint={members.length ? `${members.length} 位成员` : undefined} />
      <div className="panel">
        {myRole === 'owner' ? (
          <div className="panel__body">
            <div className="toolbar" style={{ marginBottom: 0 }}>
              <label className="field field--grow">
                <span>分享给（邮箱或昵称）</span>
                <input
                  value={account}
                  onChange={(event) => setAccount(event.target.value)}
                  onKeyDown={(event) => { if (event.key === 'Enter') void share() }}
                  placeholder="例如 teammate@example.com"
                />
              </label>
              <label className="field">
                <span>权限</span>
                <select value={role} onChange={(event) => setRole(event.target.value as typeof role)}>
                  <option value="editor">可修改</option>
                  <option value="viewer">只读</option>
                </select>
              </label>
              <button type="button" className="btn btn--primary btn--sm" onClick={() => void share()} disabled={busy || !account.trim()}>
                分享
              </button>
            </div>
            {error ? <p className="note" style={{ color: 'var(--danger)', marginTop: 8 }}>{error}</p> : null}
          </div>
        ) : (
          <div className="panel__body">
            <p className="note">
              这个课题是 {owner?.nickname ?? '别人'} 分享给你的，你的权限是
              {myRole === 'editor' ? '可修改' : '只读'}。
            </p>
          </div>
        )}
        <div className="list" style={{ borderRadius: 0, border: 0, boxShadow: 'none' }}>
          <div className="list__row" style={{ cursor: 'default' }}>
            <strong>{owner?.nickname ?? '—'}</strong>
            <span className="list__meta"><span>{owner?.email ?? ''}</span><span>属主</span></span>
          </div>
          {members.map((member) => (
            <div className="list__row" key={member.user_id} style={{ cursor: 'default' }}>
              <strong>{member.nickname}</strong>
              <span className="list__meta">
                <span>{member.email}</span>
                <span>{member.role === 'editor' ? '可修改' : '只读'}</span>
              </span>
              {myRole === 'owner' ? (
                <button
                  type="button"
                  className="tag tag--plain"
                  style={{ justifySelf: 'start' }}
                  onClick={async () => {
                    await removeProjectMember(active.project_id, member.user_id)
                    await load()
                    await refresh()
                  }}
                >
                  取消分享
                </button>
              ) : null}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

/** 语料线索：从问答、洞察、检索里攒下来的"值得再看一眼"。
 *
 *  和「已纳入的关系」是两回事：线索不改变图谱，只是记一笔。 */
function LeadsPanel({ onChanged }: { onChanged?: () => void }) {
  const { active } = useProject()
  const [leads, setLeads] = useState<ProjectLead[]>([])
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const projectId = active?.project_id ?? ''

  const load = useCallback(async () => {
    if (!projectId) { setLeads([]); return }
    try {
      setLeads((await getProjectLeads(projectId)).leads)
      setError(null)
    } catch (err) {
      setLeads([])
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [projectId])

  useEffect(() => { void load() }, [load])

  const add = async () => {
    if (!projectId || !title.trim()) return
    setBusy(true)
    try {
      await addProjectLead(projectId, { title: title.trim(), source_kind: 'manual' })
      setTitle('')
      await load()
      onChanged?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  if (!active) return null

  return (
    <div className="section">
      <SectionHead title="语料线索" hint={leads.length ? `${leads.length} 条` : undefined} />
      <div className="panel">
        <div className="panel__body">
          <div className="toolbar" style={{ marginBottom: 0 }}>
            <label className="field field--grow">
              <span>记一条线索</span>
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                onKeyDown={(event) => { if (event.key === 'Enter') void add() }}
                placeholder="例如：2025 年后有 3 篇新工作没进语料"
              />
            </label>
            <button type="button" className="btn btn--primary btn--sm" onClick={() => void add()} disabled={busy || !title.trim()}>
              记下来
            </button>
          </div>
          {error ? <p className="note" style={{ color: 'var(--danger)', marginTop: 8 }}>{error}</p> : null}
        </div>
        {leads.length === 0 ? null : (
          <div className="list list--scroll" style={{ maxHeight: 260, borderRadius: 0, border: 0, boxShadow: 'none' }}>
            {leads.map((lead) => (
              <div className="list__row" key={lead.lead_id} style={{ cursor: 'default' }}>
                <strong>{lead.title}</strong>
                <span className="list__meta">
                  <span>{lead.source_kind}</span>
                  <span>{lead.created_at.slice(0, 16).replace('T', ' ')}</span>
                </span>
                <button
                  type="button"
                  className="tag tag--plain"
                  style={{ justifySelf: 'start' }}
                  onClick={async () => {
                    await deleteProjectLead(active.project_id, lead.lead_id)
                    await load()
                    onChanged?.()
                  }}
                >
                  删掉
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

/** 模型调试：直接调一次模型接口，验证 Key 或比一句措辞。 */
function ModelPlayground() {
  const [providers, setProviders] = useState<Array<{ id: string; label: string }>>([])
  const [providerId, setProviderId] = useState('deepseek')
  const [apiKey, setApiKey] = useState('')
  const [message, setMessage] = useState('')
  const [answer, setAnswer] = useState<{ content: string; model: string; duration_ms: number } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getProviders()
      .then((payload) => {
        const list = (payload.providers ?? [])
          .filter((item) => item.id !== 'mock')
          .map((item) => ({ id: item.id, label: item.label }))
        setProviders(list)
        setProviderId((current) => (list.some((item) => item.id === current) ? current : list[0]?.id ?? 'deepseek'))
      })
      .catch(() => setProviders([]))
  }, [])

  const run = async () => {
    if (!message.trim()) return
    setBusy(true); setError(null); setAnswer(null)
    try {
      const result = await modelChat({
        provider: providerId,
        message: message.trim(),
        api_key: apiKey || undefined,
      })
      setAnswer({ content: result.content, model: result.model, duration_ms: result.duration_ms })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="section">
      <SectionHead title="模型调用" />
      <div className="panel">
        <div className="panel__body">
          <div className="toolbar" style={{ marginBottom: 10 }}>
            <label className="field">
              <span>提供方</span>
              <select value={providerId} onChange={(event) => setProviderId(event.target.value)}>
                {providers.map((item) => (
                  <option key={item.id} value={item.id}>{item.label}</option>
                ))}
              </select>
            </label>
            <label className="field field--grow">
              <span>自己的 Key（可留空，用服务器配置）</span>
              <input
                type="password"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                autoComplete="off"
                placeholder="只用于这一次请求，不保存"
              />
            </label>
          </div>
          <label className="field">
            <span>要说的话</span>
            <textarea
              rows={3}
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder="问一句，或者贴一段要改写的文字。"
            />
          </label>
          {error ? <p className="note" style={{ color: 'var(--danger)', marginTop: 8 }}>{error}</p> : null}
          {answer ? (
            <div style={{ marginTop: 10 }}>
              <p className="evi__excerpt" style={{ whiteSpace: 'pre-wrap' }}>{answer.content}</p>
              <p className="note" style={{ marginTop: 6 }}>
                {answer.model} · {Math.round(answer.duration_ms)}ms
              </p>
            </div>
          ) : null}
        </div>
        <div className="panel__foot">
          <button type="button" className="btn btn--primary btn--sm" onClick={() => void run()} disabled={busy || !message.trim()}>
            {busy ? '调用中…' : '发送'}
          </button>
        </div>
      </div>
    </div>
  )
}

/** 写作与研究技能：文献调研报告、AI 味诊断、去 AI 味。
 *
 *  这三样都来自后端既有的 `/api/skills/*`，跑的是规则与词表，不联网。
 *  产出只显示在页面上，**不会**写进课题图谱，也不会覆盖你已纳入的关系。 */
function WritingSkillsPanel() {
  const [catalogue, setCatalogue] = useState<SkillEntry[]>([])
  const domainState = useDomains()
  const domainId = domainState.domainId
  const [topic, setTopic] = useState('')
  const [discipline, setDiscipline] = useState('cs_ai')
  const [report, setReport] = useState<Record<string, unknown> | null>(null)
  const [text, setText] = useState('')
  const [diagnosis, setDiagnosis] = useState<DiagnoseReport | null>(null)
  const [revised, setRevised] = useState<HumanizeReport | null>(null)
  const [intensity, setIntensity] = useState<'light' | 'medium' | 'heavy'>('light')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getSkills().then((payload) => setCatalogue(payload.skills ?? [])).catch(() => setCatalogue([]))
  }, [])

  const act = async (kind: string, run: () => Promise<void>) => {
    setBusy(kind); setError(null)
    try { await run() } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally { setBusy('') }
  }

  return (
    <div className="section">
      <SectionHead
        title="研究与写作技能"
        hint={catalogue.length ? `后端提供 ${catalogue.length} 项` : '读取中'}
      />
      <div className="panel">
        <div className="panel__body">
          <div className="toolbar" style={{ marginBottom: 12 }}>
            <DomainSelect state={domainState} label="领域" />
            <label className="field field--grow">
              <span>调研主题</span>
              <input value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="例如：图神经网络在材料发现中的应用" />
            </label>
            <label className="field">
              <span>学科</span>
              <input value={discipline} onChange={(event) => setDiscipline(event.target.value)} />
            </label>
            <button
              type="button"
              className="btn btn--primary btn--sm"
              disabled={busy !== ''}
              onClick={() => void act('research', async () => {
                setReport(await runResearchSkill({ domain_id: domainId || null, topic, discipline }))
              })}
            >
              {busy === 'research' ? '生成中…' : '生成文献调研报告'}
            </button>
          </div>
          <CorpusNote state={domainState} />

          <label className="field">
            <span>要诊断/改写的文字</span>
            <textarea
              value={text}
              onChange={(event) => setText(event.target.value)}
              rows={4}
              placeholder="贴一段你自己写的段落。诊断看的是套路句与结构，不是判断作者是谁。"
            />
          </label>
          <div className="toolbar" style={{ marginTop: 10, marginBottom: 0 }}>
            <label className="field">
              <span>改写强度</span>
              <select value={intensity} onChange={(event) => setIntensity(event.target.value as typeof intensity)}>
                <option value="light">轻</option>
                <option value="medium">中</option>
                <option value="heavy">重</option>
              </select>
            </label>
            <button
              type="button"
              className="btn btn--quiet btn--sm"
              disabled={busy !== '' || text.trim().length < 2}
              onClick={() => void act('diagnose', async () => {
                setDiagnosis(await diagnoseText(text))
              })}
            >
              {busy === 'diagnose' ? '诊断中…' : 'AI 味诊断'}
            </button>
            <button
              type="button"
              className="btn btn--quiet btn--sm"
              disabled={busy !== '' || text.trim().length < 2}
              onClick={() => void act('humanize', async () => {
                setRevised(await humanizeText(text, intensity))
              })}
            >
              {busy === 'humanize' ? '改写中…' : '去 AI 味'}
            </button>
          </div>

          {error ? <p className="note" style={{ color: 'var(--danger)', marginTop: 10 }}>{error}</p> : null}
        </div>
        <div className="panel__foot">
        <div className="panel__foot" />
        </div>
      </div>

      {report ? (
        <div className="panel" style={{ marginTop: 12 }}>
          <div className="panel__body">
            <SectionHead title="文献调研报告" />
            <pre className="json-block">{JSON.stringify(report, null, 2).slice(0, 4000)}</pre>
          </div>
        </div>
      ) : null}

      {diagnosis ? (
        <div className="panel" style={{ marginTop: 12 }}>
          <div className="panel__body">
            <SectionHead title="AI 味诊断" />
            <pre className="json-block">{JSON.stringify(diagnosis, null, 2).slice(0, 2500)}</pre>
          </div>
        </div>
      ) : null}

      {revised ? (
        <div className="panel" style={{ marginTop: 12 }}>
          <div className="panel__body">
            <SectionHead
              title="改写结果"
              hint={`${revised.before_score} → ${revised.after_score}（降 ${revised.improvement}）`}
            />
            <p className="quote">{revised.revised}</p>
          </div>
          <div className="panel__foot">
            改写是规则替换，不保证学术表述更准确；提交前请自己读一遍。
          </div>
        </div>
      ) : null}
    </div>
  )
}

/** 设置：改名、导出、版本与保留授权。 */
export function ProjectSettingsPage() {
  const { active, projects, create, select, refresh } = useProject()
  const { graph, reload } = useProjectGraphData()
  const [archivedProjects, setArchivedProjects] = useState<Array<{ project_id: string; name: string }>>([])
  const [name, setName] = useState(active?.name ?? '')
  const [description, setDescription] = useState(active?.description ?? '')
  const [versions, setVersions] = useState<ProjectGraphVersion[]>([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [newName, setNewName] = useState('')
  const [diffFrom, setDiffFrom] = useState(1)
  const [diffTo, setDiffTo] = useState(1)
  const [diff, setDiff] = useState<VersionDiff | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [confirmClear, setConfirmClear] = useState(false)

  const loadArchived = useCallback(async () => {
    try {
      const payload = await getProjects(true)
      setArchivedProjects(
        (payload.projects ?? [])
          .filter((item) => item.archived_at)
          .map((item) => ({ project_id: item.project_id, name: item.name })),
      )
    } catch {
      setArchivedProjects([])
    }
  }, [])

  useEffect(() => { void loadArchived() }, [loadArchived])

  useEffect(() => {
    setName(active?.name ?? '')
    setDescription(active?.description ?? '')
  }, [active])

  const loadVersions = useCallback(async () => {
    if (!active) {
      setVersions([])
      return
    }
    try {
      setVersions(await getProjectGraphVersions(active.project_id))
    } catch {
      setVersions([])
    }
  }, [active])

  useEffect(() => {
    void loadVersions()
  }, [loadVersions])

  // 版本载入后给比较器一个合理的默认：最近两版
  useEffect(() => {
    if (versions.length < 2) return
    setDiffTo(versions[0].version)
    setDiffFrom(versions[1].version)
  }, [versions])

  const save = async () => {
    if (!active) return
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      await updateProject(active.project_id, { name, description })
      await refresh()
      setMessage('已保存。')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const takeSnapshot = async () => {
    if (!active) return
    setBusy(true)
    setError(null)
    try {
      const version = await snapshotProjectGraph(active.project_id)
      setMessage(`已记下一个版本：v${version.version}（${version.counts.edges} 条边）。`)
      await loadVersions()
      await reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const exportGraph = async () => {
    if (!active) return
    setBusy(true)
    setError(null)
    try {
      await downloadProjectExport(active.project_id)
      setMessage('导出已开始下载：带版本号、出处与「这是用户选择不是人工标注」的说明。')
      await loadVersions()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const exportCsv = async () => {
    if (!active) return
    setBusy(true)
    setError(null)
    try {
      await downloadProjectCsv(active.project_id)
      setMessage('CSV 已开始下载：一行一条已纳入的关系，带机器状态、你的决定与出处。')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const runDiff = async () => {
    if (!active) return
    setBusy(true)
    setError(null)
    setDiff(null)
    try {
      setDiff(await diffProjectVersions(active.project_id, diffFrom, diffTo))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const toggleArchive = async () => {
    if (!active) return
    setBusy(true)
    setError(null)
    try {
      const next = !active.archived_at
      await archiveProject(active.project_id, next)
      await refresh()
      setMessage(next ? '已归档。它从课题列表里收起来了，数据没动。' : '已取消归档。')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const clearSources = async () => {
    if (!active) return
    setBusy(true)
    setError(null)
    try {
      const result = await clearProjectSources(active.project_id)
      setMessage(`已清除 ${result.cleared} 篇论文保存的正文；证据片段保留。`)
      setConfirmClear(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const removeProject = async () => {    if (!active) return
    setBusy(true)
    setError(null)
    try {
      const result = await deleteProject(active.project_id)
      const rows = Object.values(result.rows).reduce((sum, value) => sum + value, 0)
      setMessage(`已删除课题「${result.deleted_project.name}」，连带清掉 ${rows} 行记录。`)
      setConfirmDelete(false)
      setDiff(null)
      setVersions([])
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHead
        title="设置"
        summary="课题信息、导出、版本与删除。"
      />

      {error ? <Empty title="操作失败" body={error} danger /> : null}
      {message ? <p className="note" style={{ color: 'var(--supported)', marginBottom: 14 }}>{message}</p> : null}

      <div className="grid-2" style={{ alignItems: 'start' }}>
        <div className="section">
          <SectionHead title="课题名称与说明" hint={active ? active.project_id : '未选择课题'} />
          <div className="panel">
            <div className="panel__body">
              <label className="field">
                <span>课题名称</span>
                <input value={name} onChange={(event) => setName(event.target.value)} />
              </label>
              <label className="field" style={{ marginTop: 12 }}>
                <span>这个课题要回答什么</span>
                <textarea rows={3} value={description} onChange={(event) => setDescription(event.target.value)} />
              </label>
            </div>
            <div className="panel__foot" style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
              <button type="button" className="btn btn--primary btn--sm" onClick={() => void save()} disabled={!active || busy}>
                保存
              </button>
              <span>改名不影响已纳入的关系与版本记录。</span>
            </div>
          </div>

          <SectionHead title="新建课题" hint={`现有 ${projects.length} 个`} />
          <div className="panel">
            <div className="panel__body" style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
              <label className="field field--grow">
                <span>新课题名称</span>
                <input value={newName} onChange={(event) => setNewName(event.target.value)} placeholder="例如：图神经网络在材料发现中的证据链" />
              </label>
              <button
                type="button"
                className="btn btn--primary btn--sm"
                disabled={newName.trim().length < 2 || busy}
                onClick={async () => {
                  const created = await create(newName.trim())
                  if (created) {
                    setNewName('')
                    setMessage(`已新建课题「${created.name}」并切过去。`)
                  }
                }}
              >
                新建并切换
              </button>
            </div>
            <div className="panel__foot">
              切换已有课题：
              <span style={{ marginLeft: 8, display: 'inline-flex', gap: 6, flexWrap: 'wrap' }}>
                {projects.map((project) => (
                  <button
                    key={project.project_id}
                    type="button"
                    className={active?.project_id === project.project_id ? 'tag tag--accepted' : 'tag tag--plain'}
                    onClick={() => select(project.project_id)}
                  >
                    {project.name}
                  </button>
                ))}
              </span>
            </div>
          </div>
        </div>

        <div className="section">
          <SectionHead title="导出与版本" hint={graph ? `${graph.counts.edges} 条边` : '—'} />
          <div className="panel">
            <div className="panel__body">
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                <button type="button" className="btn btn--primary btn--sm" onClick={() => void exportGraph()} disabled={!active || busy}>
                  导出图谱 JSON
                </button>
                <button type="button" className="btn btn--quiet btn--sm" onClick={() => void exportCsv()} disabled={!active || busy}>
                  导出关系表 CSV
                </button>
                <button type="button" className="btn btn--quiet btn--sm" onClick={() => void takeSnapshot()} disabled={!active || busy}>
                  记一个版本
                </button>
              </div>
              <p className="note" style={{ marginTop: 10 }}>
                导出内容是「你已纳入的关系 + 证据片段 + 版本号 + 出处」，并在文件里写明
                用户决定不等于人工科研标注。CSV 一行一条关系，带 BOM，Excel 打开中文表头不乱码。
              </p>

              {versions.length >= 2 ? (
                <>
                  <SectionHead title="比两个版本" />
                  <div className="toolbar" style={{ marginBottom: 0 }}>
                    <label className="field">
                      <span>从</span>
                      <select value={diffFrom} onChange={(event) => setDiffFrom(Number(event.target.value))}>
                        {versions.map((version) => (
                          <option key={version.version_id} value={version.version}>v{version.version}</option>
                        ))}
                      </select>
                    </label>
                    <label className="field">
                      <span>到</span>
                      <select value={diffTo} onChange={(event) => setDiffTo(Number(event.target.value))}>
                        {versions.map((version) => (
                          <option key={version.version_id} value={version.version}>v{version.version}</option>
                        ))}
                      </select>
                    </label>
                    <button
                      type="button"
                      className="btn btn--quiet btn--sm"
                      onClick={() => void runDiff()}
                      disabled={busy || diffFrom === diffTo}
                    >
                      比较
                    </button>
                  </div>
                  {diff ? (
                    <div style={{ marginTop: 10 }}>
                      <p className="note">
                        v{diff.from_version} → v{diff.to_version}：新增 {diff.added_count} 条、
                        移除 {diff.removed_count} 条、保持不变 {diff.unchanged_count} 条。
                      </p>
                      {diff.added.length > 0 ? (
                        <p className="note" style={{ color: 'var(--supported)' }}>
                          新增：{diff.added.join('、')}
                        </p>
                      ) : null}
                      {diff.removed.length > 0 ? (
                        <p className="note" style={{ color: 'var(--danger)' }}>
                          移除：{diff.removed.join('、')}
                        </p>
                      ) : null}
                    </div>
                  ) : null}
                </>
              ) : (
                <p className="note" style={{ marginTop: 10 }}>
                  记满两个版本，才能比出多了哪几条、少了哪几条。
                </p>
              )}

              <div className="list list--scroll" style={{ marginTop: 12, maxHeight: 260 }}>
                {versions.length === 0 ? (
                  <div className="list__row" style={{ cursor: 'default' }}>
                    <span className="note">还没有版本记录。导出或点「记一个版本」会生成一条。</span>
                  </div>
                ) : (
                  versions.map((version) => (
                    <div className="list__row" key={version.version_id} style={{ cursor: 'default' }}>
                      <strong>v{version.version}</strong>
                      <span className="list__meta">
                        <span>{version.counts.edges} 条边</span>
                        <span>{version.counts.included} 条纳入关系</span>
                        <span className="mono">{version.created_at}</span>
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>

          <SectionHead title="数据保留" />
          <div className="panel">
            <div className="panel__body">
              <ul className="checklist">
                <li><i>·</i><span>整篇论文正文默认不落盘；只有读入时勾了「允许保存原文」才会写进本机数据库。</span></li>
                <li><i>·</i><span>证据片段（一句话引用）随关系一起保存，用于日后核对原文位置。</span></li>
                <li><i>·</i><span>你的决定与人工标注答案分开存放，导出文件里也会标明这一点。</span></li>
                <li><i>·</i><span>删除课题会连带删掉它的论文归属、候选关系、证据引用、决定与版本记录，见下面「删除课题」一节；没有回收站。</span></li>
              </ul>
            </div>
          </div>
        </div>
      </div>

      <div className="section" style={{ marginTop: 24 }}>
        <SectionHead title="归档与删除" hint="归档可撤销，删除不可撤销" />
        <div className="panel">
          <div className="panel__body" style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
            <button
              type="button"
              className="btn btn--quiet btn--sm"
              onClick={() => void toggleArchive()}
              disabled={!active || busy}
            >
              {active?.archived_at ? '取消归档' : '归档这个课题'}
            </button>
            <span className="note">
              {active?.archived_at
                ? '已归档：它不在课题列表里，但数据都还在；取消归档就能重新打开。'
                : '归档只是收起来，论文、关系、决定、版本一行都不删。'}
            </span>
          </div>
          {archivedProjects.length > 0 ? (
            <div className="panel__foot">
              <span>已归档的课题：</span>
              <span style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap', marginLeft: 8 }}>
                {archivedProjects.map((item) => (
                  <button
                    key={item.project_id}
                    type="button"
                    className="tag tag--plain"
                    onClick={async () => {
                      await archiveProject(item.project_id, false)
                      await loadArchived()
                      await refresh()
                    }}
                  >
                    {item.name} · 取消归档
                  </button>
                ))}
              </span>
            </div>
          ) : null}
        </div>
        <div className="panel blocked" style={{ marginTop: 12 }}>
          <div className="panel__body">
            <p className="note">
              删除会连带清掉论文归属、候选关系、证据引用、你的决定与所有版本记录，没有回收站。
              只想暂时收起来，用上面的归档。
            </p>
            {confirmDelete ? (
              <div className="toolbar" style={{ marginTop: 12, marginBottom: 0 }}>
                <button type="button" className="btn btn--primary btn--sm" onClick={() => void removeProject()} disabled={busy}>
                  确认删除「{active?.name}」
                </button>
                <button type="button" className="btn btn--quiet btn--sm" onClick={() => setConfirmDelete(false)} disabled={busy}>
                  先不删
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="btn btn--quiet btn--sm"
                style={{ marginTop: 12 }}
                onClick={() => setConfirmDelete(true)}
                disabled={!active}
              >
                删除当前课题…
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="section" style={{ marginTop: 24 }}>
        <SectionHead title="已保存的论文正文" hint="只清正文，证据片段保留" />
        <div className="panel">
          <div className="panel__body">
            <p className="note">
              这里清掉的是读入时保存的正文，关系与证据片段不受影响。
            </p>
            {confirmClear ? (
              <div className="toolbar" style={{ marginTop: 12, marginBottom: 0 }}>
                <button type="button" className="btn btn--primary btn--sm" onClick={() => void clearSources()} disabled={busy}>
                  确认清除
                </button>
                <button type="button" className="btn btn--quiet btn--sm" onClick={() => setConfirmClear(false)} disabled={busy}>
                  先不清
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="btn btn--quiet btn--sm"
                style={{ marginTop: 12 }}
                onClick={() => setConfirmClear(true)}
                disabled={!active}
              >
                清除已保存的正文…
              </button>
            )}
          </div>
        </div>
      </div>

      <ModelPlayground />

      <DomainPanel />

      <SharePanel />

      <PhonePanel />

      <ServiceStatusPanel />
    </>
  )
}

/** 研究领域：用户自己起的领域列在这里，可新建、可删除。
 *
 *  这里只管名字。删掉一个领域不会动课题里的论文、候选关系与证据——
 *  那几样都存在课题自己名下，领域只是个归类。 */
function DomainPanel() {
  const state = useDomains()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  const custom = state.domains.filter((item) => item.custom)

  const create = async () => {
    setBusy('create'); setError(null)
    try {
      await state.create(name.trim(), description.trim())
      setName(''); setDescription('')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally { setBusy('') }
  }

  const remove = async (domainId: string) => {
    setBusy(domainId); setError(null)
    try {
      await state.remove(domainId)
      setConfirmDelete(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally { setBusy('') }
  }

  return (
    <div className="section" style={{ marginTop: 24 }}>
      <SectionHead title="研究领域" hint={`${custom.length} 个`} />
      <div className="panel">
        <div className="panel__body">
          <div className="toolbar" style={{ marginBottom: 12 }}>
            <label className="field field--grow">
              <span>新建一个研究领域</span>
              <input
                value={name}
                maxLength={40}
                placeholder="例如：蛋白质相分离与凝胶化"
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label className="field field--grow">
              <span>一句话说明（可选）</span>
              <input
                value={description}
                maxLength={200}
                placeholder="这个方向你在研究什么"
                onChange={(event) => setDescription(event.target.value)}
              />
            </label>
            <button
              type="button"
              className="btn btn--primary btn--sm"
              disabled={busy !== '' || name.trim().length < 2}
              onClick={() => void create()}
            >
              {busy === 'create' ? '建中…' : '建好'}
            </button>
          </div>
          {error ? <p className="note" style={{ color: 'var(--danger)', marginBottom: 10 }}>{error}</p> : null}

          <dl className="kv">
            <dt>已建领域</dt>
            <dd>{custom.length ? `${custom.length} 个，列在下面` : '还没有'}</dd>
          </dl>

          {custom.length === 0 ? (
            <p className="note" style={{ marginTop: 12 }}>
              研究领域不在列表里时，在上面填个名字建一个，建好会自动出现在各页的下拉框里。
            </p>
          ) : (
            <ul className="list" style={{ marginTop: 12 }}>
              {custom.map((item) => (
                <li key={item.id} className="list__row" style={{ cursor: 'default' }}>
                  <div>
                    <strong>{item.name}</strong>
                    <span className="list__meta">{item.description || '没有写说明'}</span>
                  </div>
                  {confirmDelete === item.id ? (
                    <span className="toolbar" style={{ marginBottom: 0 }}>
                      <button
                        type="button"
                        className="btn btn--primary btn--sm"
                        disabled={busy !== ''}
                        onClick={() => void remove(item.id)}
                      >
                        确认删掉
                      </button>
                      <button
                        type="button"
                        className="btn btn--quiet btn--sm"
                        onClick={() => setConfirmDelete(null)}
                      >
                        先不删
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="btn btn--quiet btn--sm"
                      onClick={() => setConfirmDelete(item.id)}
                    >
                      删除
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
          {custom.length > 0 ? (
            <p className="note" style={{ marginTop: 10 }}>
              删除只去掉这个名字，课题里的论文与关系不受影响。
            </p>
          ) : null}
        </div>
      </div>
    </div>
  )
}

/** 手机上怎么连进来：给出同一 WiFi 下能直接打开的网址。
 *
 *  服务只绑了本机回环时先不显示地址——给一个手机打不开的网址比不给更糟。
 *  复制走 clipboard，局域网 http 下浏览器不给用就静默算了，网址本来就摆在页面上。 */
function PhonePanel() {
  const [access, setAccess] = useState<SystemAccess | null>(null)
  const [copied, setCopied] = useState<string | null>(null)

  useEffect(() => {
    getSystemAccess().then(setAccess).catch(() => setAccess(null))
  }, [])

  const copy = async (url: string) => {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(url)
      window.setTimeout(() => setCopied((current) => (current === url ? null : current)), 2400)
    } catch {
      setCopied(null)
    }
  }

  const addresses = access?.addresses ?? []

  return (
    <div className="section" style={{ marginTop: 24 }}>
      <SectionHead title="手机上用" hint="手机和电脑连同一个 WiFi" />
      <div className="panel">
        <div className="panel__body">
          {addresses.length > 0 ? (
            <>
              <div className="toolbar" style={{ marginBottom: 12 }}>
                {addresses.map((url) => (
                  <span key={url} className="toolbar" style={{ gap: 8, marginBottom: 0 }}>
                    <code className="mono" style={{ fontSize: 15 }}>{url}</code>
                    <button type="button" className="btn btn--quiet btn--sm" onClick={() => void copy(url)}>
                      {copied === url ? '已复制' : '复制'}
                    </button>
                  </span>
                ))}
              </div>
              <p className="note">
                用手机浏览器打开上面的网址，选「添加到主屏幕」，以后从桌面图标进。
              </p>
            </>
          ) : access ? (
            <p className="note">
              这次启动只对本机开放，手机连不上。要用手机版，关掉现在的窗口，
              用根目录的「启动手机版.bat」重新开一次，这里就会显示网址。
            </p>
          ) : (
            <p className="note">读不到本机地址。</p>
          )}
        </div>
      </div>
    </div>
  )
}

/** 服务与账号状态：把后端的 ready / auth/status / 当前画像读出来摆在这里。
 *
 *  这几样都是只读体检项：能看出后端哪个部件没起来、注册是不是关着、
 *  当前账号的画像版本是多少。 */
function ServiceStatusPanel() {
  const [ready, setReady] = useState<ReadinessReport | null>(null)
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null)
  const [profile, setProfile] = useState<LearnerProfile | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getReadiness().then(setReady).catch((err: Error) => setError(err.message))
    getAuthStatus().then(setAuthStatus).catch(() => setAuthStatus(null))
    getMyProfile().then(setProfile).catch(() => setProfile(null))
  }, [])

  return (
    <div className="section" style={{ marginTop: 24 }}>
      <SectionHead title="服务与账号状态" />
      <div className="panel">
        <div className="panel__body">
          <dl className="kv">
            <dt>服务状态</dt>
            <dd>{ready ? ready.status : '—'}</dd>
            <dt>知识库</dt>
            <dd>{ready ? (ready.checks.knowledge_base ? '可用' : '未就绪') : '—'}</dd>
            <dt>画像</dt>
            <dd>{ready ? (ready.checks.profiles ? '可用' : '未就绪') : '—'}</dd>
            <dt>数据库</dt>
            <dd>{ready ? (ready.checks.database ? '可用' : '未就绪') : '—'}</dd>
            <dt>注册</dt>
            <dd>{authStatus ? (authStatus.registration_open ? '开放注册' : '由管理员分配') : '—'}</dd>
            <dt>当前画像</dt>
            <dd>{profile ? `${profile.name} · 难度 ${profile.expected_difficulty}/5` : '—'}</dd>
            <dt>画像编号</dt>
            <dd className="mono">{profile?.profile_id ?? '—'}</dd>
          </dl>
          {error ? <p className="note" style={{ color: 'var(--danger)', marginTop: 10 }}>{error}</p> : null}
        </div>
        <div className="panel__foot">
        </div>
      </div>
    </div>
  )
}
