import type {
  AgentTraceStep,
  PanelCounts,
  PanelMessage,
  PanelResult,
  PanelVerdict,
  AtlasDomainData,
  AtlasDomainSummary,
  AuthState,
  AuthStatus,
  DiagnoseReport,
  Domain,
  ExperimentLedger,
  ExtractedGraphPayload,
  GraphInsightPayload,
  Health,
  HumanizeReport,
  IngestResult,
  IngestionSummaryRow,
  LearnerProfile,
  LlmConfig,
  OnlineRagPayload,
  Project,
  ProjectEvidenceRef,
  ProjectGraph,
  ProjectGraphVersion,
  ProjectPaper,
  ProjectRelation,
  ProviderInfo,
  ProviderTestResult,
  ReadinessReport,
  RelationDecision,
  ResearchProgressEvent,
  RunResult,
  SkillEntry,
  SystemAccess,
  UserAccount,
} from './types'

const jsonHeaders = { 'Content-Type': 'application/json; charset=utf-8' }
const apiPrefix = window.location.pathname.startsWith('/AgentDemo/start') ? '/AgentDemo/start/api' : '/api'
const apiPath = (path: string) => path.replace(/^\/api/, apiPrefix)

/** 后端返回的结构化错误：带状态码与业务码，好让页面按原因分别显示。 */
export class ApiError extends Error {
  status: number
  code: string
  retryable: boolean

  constructor(status: number, code: string, message: string, retryable = false) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.retryable = retryable
  }
}

/** nginx 挡掉的请求（413/429）返回的是它自己的 HTML 页，拿不到 JSON 里的 code；
 *  这里按状态码写成用户能看懂的一句话，免得界面上出现 `413 Request Entity Too Large`。 */
function plainHttpMessage(status: number): string {
  if (status === 413) return '文件太大，服务器拒收。请压缩这个 PDF，或换一篇再试。'
  if (status === 429) return '请求太快，服务器要求稍等再发。'
  if (status === 502 || status === 503 || status === 504) return '服务器暂时不可用，稍后再试。'
  return ''
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiPath(path), { credentials: 'include', ...init })
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as
      | { error?: { code?: string; message?: string; retryable?: boolean } }
      | null
    throw new ApiError(
      response.status,
      payload?.error?.code || `http_${response.status}`,
      payload?.error?.message ||
        plainHttpMessage(response.status) ||
        `${response.status} ${response.statusText}`,
      Boolean(payload?.error?.retryable),
    )
  }
  return response.json() as Promise<T>
}

export const getHealth = (): Promise<Health> => request('/api/health')
export const getAuth = (): Promise<AuthState> => request('/api/auth/me')
export const login = (identifier: string, password: string): Promise<AuthState> =>
  request('/api/auth/login', { method: 'POST', headers: jsonHeaders, body: JSON.stringify({ identifier, password }) })
export const logout = (): Promise<AuthState> => request('/api/auth/logout', { method: 'POST' })
export const updateProfile = (profile: LearnerProfile): Promise<{ profile: LearnerProfile } & UserAccount> =>
  request('/api/me/profile', { method: 'PUT', headers: jsonHeaders, body: JSON.stringify(profile) })

export function getProfiles(): Promise<LearnerProfile[]> {
  return request('/api/profiles')
}

export function getDomains(): Promise<Domain[]> {
  return request('/api/domains')
}

/** 建一个自定义研究领域。只存名字与一句话说明，不会生成语料。 */
export function createDomain(payload: {
  domain_name: string
  description?: string
}): Promise<Domain> {
  return request('/api/domains', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  })
}

export function deleteDomain(domainId: string): Promise<{ domain_id: string; removed: boolean }> {
  return request(`/api/domains/${encodeURIComponent(domainId)}`, { method: 'DELETE' })
}

export function getProviders(): Promise<{ providers: ProviderInfo[]; free_deepseek_ready: boolean }> {
  return request('/api/providers')
}

export function testProvider(config: LlmConfig): Promise<ProviderTestResult> {
  return request('/api/provider/test', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(config),
  })
}

export function getExperimentLedger(): Promise<ExperimentLedger> {
  return request('/api/experiments')
}

export function getAblation(): Promise<Record<string, unknown>> {
  return request('/api/ablation')
}

export function getHistory(
  limit = 50,
  projectId?: string,
): Promise<Array<Record<string, unknown>>> {
  const params = new URLSearchParams({ limit: String(limit) })
  if (projectId) params.set('project_id', projectId)
  return request(`/api/history?${params.toString()}`)
}

export function getIngestions(
  limit = 50,
  projectId?: string,
): Promise<IngestionSummaryRow[]> {
  const params = new URLSearchParams({ limit: String(limit) })
  if (projectId) params.set('project_id', projectId)
  return request(`/api/ingestions?${params.toString()}`)
}

export function getExtractedGraph(domainId?: string | null): Promise<ExtractedGraphPayload> {
  const suffix = domainId ? `?domain_id=${encodeURIComponent(domainId)}` : ''
  return request<ExtractedGraphPayload>(`/api/extracted-graph${suffix}`)
}

export const getReadiness = (): Promise<ReadinessReport> => request('/api/ready')
export const getAuthStatus = (): Promise<AuthStatus> => request('/api/auth/status')
export const getSystemAccess = (): Promise<SystemAccess> => request('/api/system/access')
export const bootstrapAccount = (payload: {
  email: string
  nickname: string
  password: string
}): Promise<AuthState> =>
  request('/api/auth/bootstrap', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  })
export const getMyProfile = (): Promise<LearnerProfile> => request('/api/me/profile')

export const getSkills = (): Promise<{ skills: SkillEntry[] }> => request('/api/skills')

export const runResearchSkill = (payload: {
  domain_id?: string | null
  topic?: string
  discipline?: string
}): Promise<Record<string, unknown>> =>
  request('/api/skills/research', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  })

export const diagnoseText = (text: string): Promise<DiagnoseReport> =>
  request('/api/skills/diagnose', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ text }),
  })

export const humanizeText = (text: string, intensity: 'light' | 'medium' | 'heavy'): Promise<HumanizeReport> =>
  request('/api/skills/humanize', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ text, intensity }),
  })

export function extractPdfTables(file: File, extractTables = true): Promise<Record<string, unknown>> {
  const form = new FormData()
  form.append('file', file)
  form.append('extract_tables', String(extractTables))
  return request('/api/skills/pdf/extract', { method: 'POST', body: form })
}

/** 公开注册：建号并直接登录。服务端开关关着时会回 403。 */
export const registerAccount = (payload: {
  email: string
  nickname: string
  password: string
}): Promise<AuthState> =>
  request('/api/auth/register', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  })

export const getHistoryDetail = (researchSessionId: string): Promise<Record<string, unknown>> =>
  request(`/api/history/${encodeURIComponent(researchSessionId)}`)

export const searchOnline = (payload: {
  query: string
  limit?: number
  allow_network: boolean
}): Promise<OnlineRagPayload> =>
  request('/api/online-rag', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload) })

export const queryGraph = (payload: {
  query: string
  domain_id?: string | null
}): Promise<Record<string, unknown>> =>
  request('/api/graph-query', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload) })

export function getGraphInsights(
  query: string,
  domainId?: string | null,
): Promise<GraphInsightPayload> {
  const params = new URLSearchParams({ query })
  if (domainId) params.set('domain_id', domainId)
  return request(`/api/graph-insights?${params.toString()}`)
}

export const sendFeedback = (payload: {
  profile_id: string
  query: string
  domain_id?: string | null
  feedback: 'too_hard' | 'suitable' | 'too_easy'
}): Promise<RunResult> =>
  request('/api/feedback', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload) })

export interface ProviderPayload {
  provider: string
  model?: string
  api_key?: string
  timeout_seconds?: number
}

export interface RunPayload {
  profile_id: string
  query: string
  domain_id?: string | null
  include_ablation?: boolean
  llm?: LlmConfig | null
  project_id?: string | null
}

export const runPipeline = (payload: RunPayload): Promise<RunResult> =>
  request('/api/run', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload) })

export async function streamPipeline(
  payload: RunPayload,
  handlers: {
    onStarted?: (operationId: string) => void
    onStep?: (step: AgentTraceStep) => void
    onProgress?: (progress: ResearchProgressEvent) => void
    onHeartbeat?: (elapsedMs: number) => void
  },
): Promise<RunResult> {
  const response = await fetch(apiPath('/api/run/stream'), {
    method: 'POST', credentials: 'include', headers: { ...jsonHeaders, Accept: 'text/event-stream' }, body: JSON.stringify(payload),
  })
  if (!response.ok || !response.body) {
    const error = await response.json().catch(() => null) as { error?: { message?: string } } | null
    throw new Error(error?.error?.message || `流式运行失败（HTTP ${response.status}）`)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result: RunResult | null = null
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() ?? ''
    for (const block of blocks) {
      const event = block.match(/^event:\s*(.+)$/m)?.[1]
      const raw = block.match(/^data:\s*(.+)$/m)?.[1]
      if (!event || !raw) continue
      const data = JSON.parse(raw) as Record<string, unknown>
      if (event === 'started') handlers.onStarted?.(String(data.operation_id ?? ''))
      if (event === 'agent_step') handlers.onStep?.(data.step as AgentTraceStep)
      if (event === 'progress') handlers.onProgress?.(data.progress as ResearchProgressEvent)
      if (event === 'heartbeat') handlers.onHeartbeat?.(Number(data.elapsed_ms ?? 0))
      if (event === 'error') throw new Error(String(data.message ?? '运行中断'))
      if (event === 'completed') result = data.result as RunResult
    }
    if (done) break
  }
  if (!result) throw new Error('运行流已结束，但没有收到完成结果。')
  return result
}

export interface IngestPayload {
  paper_id: string
  title: string
  text: string
  profile_id: string
  accept_threshold: number
  llm?: LlmConfig | null
  save_source?: boolean
  project_id?: string | null
}

export const ingestPaper = (payload: IngestPayload): Promise<IngestResult> =>
  request('/api/ingest-paper', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload) })

export function ingestPdf(payload: {
  file: File
  profile_id: string
  paper_id: string
  title: string
  accept_threshold: number
  llm?: LlmConfig | null
  save_source?: boolean
  project_id?: string | null
}): Promise<IngestResult> {
  const form = new FormData()
  form.append('file', payload.file)
  form.append('profile_id', payload.profile_id)
  form.append('paper_id', payload.paper_id)
  form.append('title', payload.title)
  form.append('accept_threshold', String(payload.accept_threshold))
  if (payload.llm) form.append('llm', JSON.stringify(payload.llm))
  form.append('save_source', String(payload.save_source ?? false))
  if (payload.project_id) form.append('project_id', payload.project_id)
  return request('/api/ingest-pdf', { method: 'POST', body: form })
}

export function getAtlasDomains(): Promise<{ domains: AtlasDomainSummary[] }> {
  return request('/api/atlas/domains')
}

export function getAtlasDomain(domainId: string): Promise<AtlasDomainData> {
  return request(`/api/atlas/${encodeURIComponent(domainId)}`)
}

// —— 项目与个人图谱（SCHEMA_VERSION 4）——

export function getProjects(includeArchived = false): Promise<{ projects: Project[] }> {
  const suffix = includeArchived ? '?include_archived=true' : ''
  return request(`/api/projects${suffix}`)
}
export function archiveProject(projectId: string, archived: boolean): Promise<Project> {
  return request(`/api/projects/${encodeURIComponent(projectId)}/archive`, {
    method: 'PATCH',
    headers: jsonHeaders,
    body: JSON.stringify({ archived }),
  })
}

export interface ProjectMember {
  user_id: string
  nickname: string
  email: string
  role: string
  added_at?: string
}

export function getProjectMembers(projectId: string): Promise<{
  owner: ProjectMember | null
  members: ProjectMember[]
  my_role: string
}> {
  return request(`/api/projects/${encodeURIComponent(projectId)}/members`)
}

export function addProjectMember(
  projectId: string,
  account: string,
  role: 'editor' | 'viewer' = 'editor',
): Promise<ProjectMember> {
  return request(`/api/projects/${encodeURIComponent(projectId)}/members`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ account, role }),
  })
}

export function removeProjectMember(
  projectId: string,
  memberUserId: string,
): Promise<{ removed: boolean }> {
  return request(
    `/api/projects/${encodeURIComponent(projectId)}/members/${encodeURIComponent(memberUserId)}`,
    { method: 'DELETE' },
  )
}

export interface ProjectLead {
  lead_id: string
  source_kind: string
  title: string
  detail: string
  created_at: string
}

export function getProjectLeads(projectId: string): Promise<{ leads: ProjectLead[]; count: number }> {
  return request(`/api/projects/${encodeURIComponent(projectId)}/leads`)
}

export function addProjectLead(
  projectId: string,
  payload: { title: string; detail?: string; source_kind?: string },
): Promise<ProjectLead> {
  return request(`/api/projects/${encodeURIComponent(projectId)}/leads`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  })
}

export function deleteProjectLead(projectId: string, leadId: string): Promise<{ removed: boolean }> {
  return request(
    `/api/projects/${encodeURIComponent(projectId)}/leads/${encodeURIComponent(leadId)}`,
    { method: 'DELETE' },
  )
}

export function clearProjectSources(projectId: string): Promise<{ cleared: number }> {
  return request(`/api/projects/${encodeURIComponent(projectId)}/sources`, { method: 'DELETE' })
}

export function adoptRunClaims(
  projectId: string,
  payload: { run_id: string; claims: Array<Record<string, unknown>> },
): Promise<{ candidates_added: number; candidates_total: number }> {
  return request(`/api/projects/${encodeURIComponent(projectId)}/claims`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  })
}

export function modelChat(payload: {
  provider: string
  model?: string
  message: string
  system?: string
  api_key?: string
}): Promise<{
  content: string
  provider: string
  model: string
  access_mode?: string
  duration_ms: number
  usage?: Record<string, number>
}> {
  return request('/api/model/chat', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  })
}

export function createProject(payload: { name: string; description?: string }): Promise<Project> {
  return request('/api/projects', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  })
}

export function updateProject(
  projectId: string,
  payload: { name?: string; description?: string },
): Promise<Project> {
  return request(`/api/projects/${encodeURIComponent(projectId)}`, {
    method: 'PATCH',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  })
}

export function getProjectPapers(projectId: string): Promise<ProjectPaper[]> {
  return request(`/api/projects/${encodeURIComponent(projectId)}/papers`)
}

/** 把这篇论文从课题里删掉（连带它的候选关系、证据引用与你的决定）。 */
export function removeProjectPaper(
  projectId: string,
  paperId: string,
): Promise<{ paper_id: string; title: string; removed: boolean; rows: Record<string, number> }> {
  return request(
    `/api/projects/${encodeURIComponent(projectId)}/papers/${encodeURIComponent(paperId)}`,
    { method: 'DELETE' },
  )
}

export function addProjectPapers(
  projectId: string,
  papers: Array<{ paper_id: string; title: string; source_kind?: string }>,
  options?: { source?: 'corpus' | 'knowledge_db'; domainId?: string; includeAll?: boolean },
): Promise<{
  papers: ProjectPaper[]
  source: string
  domain_id: string | null
  candidates_total: number
  candidates_added: number
  note: string
}> {
  return request(`/api/projects/${encodeURIComponent(projectId)}/papers`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({
      papers,
      source: options?.source ?? 'corpus',
      domain_id: options?.domainId ?? null,
      include_all: options?.includeAll ?? false,
    }),
  })
}

export interface KnowledgeStoreCounts {
  papers: number
  sections: number
  evidence: number
  entities: number
  relations: number
  relation_evidence: number
}

export interface KnowledgeStoreDomain {
  domain_id: string
  path: string
  exists: boolean
  bytes?: number
  modified_at?: number
  counts: KnowledgeStoreCounts | null
  error?: string
}

export interface KnowledgeStoreSummary {
  root: string
  domains: KnowledgeStoreDomain[]
  totals: KnowledgeStoreCounts
  tables: string[]
}

export function getKnowledgeStoreSummary(): Promise<KnowledgeStoreSummary> {
  return request('/api/knowledge-store/summary')
}

export function getKnowledgeStorePapers(
  domainId: string,
  limit = 500,
): Promise<{
  domain_id: string
  count: number
  papers: Array<{
    paper_id: string
    title: string
    source_url: string
    evidence_count: number
    relation_count: number
  }>
}> {
  return request(
    `/api/knowledge-store/${encodeURIComponent(domainId)}/papers?limit=${limit}`,
  )
}

export interface StoreQualityDomain {
  domain_id: string
  exists: boolean
  evidence_total: number
  citation_like: number
  share: number
  samples: Array<{ evidence_id: string; paper_id: string; text: string }>
}

export interface StoreQuality {
  domains: StoreQualityDomain[]
  evidence_total: number
  citation_like: number
  share: number
  judged_by: string
  note: string
}

export function getKnowledgeStoreQuality(): Promise<StoreQuality> {
  return request('/api/knowledge-store/quality')
}

// —— 研海 Lab（独立服务，默认 8767）——

/** Lab 跑在另一个端口上；同机部署时按当前 hostname 推出来。 */
export const LAB_BASE = (() => {
  if (typeof window === 'undefined') return 'http://127.0.0.1:8767'
  const { protocol, hostname } = window.location
  return `${protocol}//${hostname || '127.0.0.1'}:8767`
})()

export class LabUnavailable extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'LabUnavailable'
  }
}

async function labRequest<T>(path: string): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${LAB_BASE}${path}`, { credentials: 'include' })
  } catch {
    // 连不上＝Lab 服务没起，和"没权限"是两件事
    throw new LabUnavailable(`连不上研海 Lab 服务（${LAB_BASE}）`)
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | { detail?: { code?: string; message?: string } }
      | null
    throw new ApiError(
      response.status,
      payload?.detail?.code || `http_${response.status}`,
      payload?.detail?.message || `${response.status} ${response.statusText}`,
    )
  }
  return response.json() as Promise<T>
}

export const getLabHealth = (): Promise<{ status: string; service: string; version: string }> =>
  labRequest('/api/lab/health')

export const getLabExperiments = (): Promise<ExperimentLedger> =>
  labRequest('/api/lab/experiments')

export const getLabAblation = (): Promise<Record<string, unknown>> =>
  labRequest('/api/lab/ablation')

export const getLabStoreQuality = (): Promise<StoreQuality> =>
  labRequest('/api/lab/store-quality')

export const getLabGoldInventory = (): Promise<{
  root: string
  count: number
  entries: Array<{ path: string; bytes: number; sha256_prefix: string; suffix: string }>
  note: string
}> => labRequest('/api/lab/gold-inventory')

export function getProjectRelations(
  projectId: string,
  decision?: RelationDecision | 'undecided',
): Promise<{ relations: ProjectRelation[]; count: number }> {
  const suffix = decision ? `?decision=${encodeURIComponent(decision)}` : ''
  return request(`/api/projects/${encodeURIComponent(projectId)}/relations${suffix}`)
}

export function getRelationEvidence(
  projectId: string,
  relationId: string,
): Promise<{ relation_id: string; evidence: ProjectEvidenceRef[]; count: number }> {
  return request(
    `/api/projects/${encodeURIComponent(projectId)}/relations/${encodeURIComponent(relationId)}/evidence`,
  )
}

export function decideRelation(
  projectId: string,
  relationId: string,
  decision: RelationDecision,
  note = '',
): Promise<{ relation_id: string; decision: RelationDecision; decided_at: string }> {
  return request(
    `/api/projects/${encodeURIComponent(projectId)}/relations/${encodeURIComponent(relationId)}/decision`,
    { method: 'POST', headers: jsonHeaders, body: JSON.stringify({ decision, note }) },
  )
}

export function clearRelationDecision(
  projectId: string,
  relationId: string,
): Promise<{ relation_id: string; cleared: boolean }> {
  return request(
    `/api/projects/${encodeURIComponent(projectId)}/relations/${encodeURIComponent(relationId)}/decision`,
    { method: 'DELETE' },
  )
}

export function getProjectGraph(projectId: string): Promise<ProjectGraph> {
  return request(`/api/projects/${encodeURIComponent(projectId)}/graph`)
}

export function getProjectGraphVersions(projectId: string): Promise<ProjectGraphVersion[]> {
  return request(`/api/projects/${encodeURIComponent(projectId)}/graph/versions`)
}

export interface EvidenceContextPayload {
  evidence_id: string
  relation_id: string
  paper_id: string
  section_id: string
  char_start: number
  char_end: number
  text: string
  context: string
  context_start: number
  context_end: number
  document_length?: number
  source: 'stored_source' | 'corpus_card' | 'unavailable'
  note: string
}

export function getEvidenceContext(
  projectId: string,
  evidenceId: string,
  window = 400,
): Promise<EvidenceContextPayload> {
  const params = new URLSearchParams({ project_id: projectId, window: String(window) })
  return request(
    `/api/evidence/${encodeURIComponent(evidenceId)}/context?${params.toString()}`,
  )
}

export interface VersionDiff {
  from_version: number
  to_version: number
  added: string[]
  removed: string[]
  added_count: number
  removed_count: number
  unchanged_count: number
  counts: { from: Record<string, number> | null; to: Record<string, number> | null }
}

export function diffProjectVersions(
  projectId: string,
  fromVersion: number,
  toVersion: number,
): Promise<VersionDiff> {
  const params = new URLSearchParams({
    from_version: String(fromVersion),
    to_version: String(toVersion),
  })
  return request(
    `/api/projects/${encodeURIComponent(projectId)}/graph/diff?${params.toString()}`,
  )
}

export function deleteProject(projectId: string): Promise<{
  deleted_project: { project_id: string; name: string }
  rows: Record<string, number>
}> {
  return request(`/api/projects/${encodeURIComponent(projectId)}`, { method: 'DELETE' })
}

/** 下载 CSV：走 Blob，和 JSON 导出一样由浏览器落地。 */
export async function downloadProjectCsv(projectId: string): Promise<void> {
  const response = await fetch(
    apiPath(`/api/projects/${encodeURIComponent(projectId)}/export.csv`),
    { credentials: 'include' },
  )
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: { message?: string } } | null
    throw new Error(payload?.error?.message || `${response.status} ${response.statusText}`)
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `yanhai-graph-${projectId}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export function snapshotProjectGraph(projectId: string): Promise<ProjectGraphVersion> {
  return request(`/api/projects/${encodeURIComponent(projectId)}/graph/versions`, { method: 'POST' })
}

export async function downloadProjectExport(projectId: string): Promise<void> {
  const response = await fetch(
    apiPath(`/api/projects/${encodeURIComponent(projectId)}/export`),
    { credentials: 'include' },
  )
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: { message?: string } } | null
    throw new Error(payload?.error?.message || `${response.status} ${response.statusText}`)
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `yanhai-graph-${projectId}.json`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export function getIngestion(ingestionId: string): Promise<{
  ingestion_id: string
  project_id: string | null
  paper_id: string
  title: string
  source_kind: string
  source_saved: boolean
  created_at: string
  result: Record<string, unknown>
}> {
  return request(`/api/ingestions/${encodeURIComponent(ingestionId)}`)
}
// —— AI 组会 ——

/** 开一次 AI 组会（流式）。消息一条条回来，最后给出整场的计数与判定。 */
export async function streamPanel(
  projectId: string,
  payload: { limit: number; only: 'needs_review' | 'undecided' | 'all'; paper_id?: string },
  handlers: { onMessage?: (message: PanelMessage) => void } = {},
): Promise<PanelResult> {
  const response = await fetch(apiPath(`/api/projects/${encodeURIComponent(projectId)}/panel/stream`), {
    method: 'POST',
    credentials: 'include',
    headers: { ...jsonHeaders, Accept: 'text/event-stream' },
    body: JSON.stringify({ ...payload, decision_mode: 'auto' }),
  })
  if (!response.ok || !response.body) {
    const error = (await response.json().catch(() => null)) as { error?: { message?: string } } | null
    throw new Error(error?.error?.message || `组会没开成（HTTP ${response.status}）`)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const messages: PanelMessage[] = []
  const verdicts: PanelVerdict[] = []
  let mode = 'rules'
  let modeLabel = '规则裁判'
  let counts: PanelCounts = { processed: 0, remaining: 0, accepted: 0, needs_review: 0, rejected: 0 }
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() ?? ''
    for (const block of blocks) {
      const event = block.match(/^event:\s*(.+)$/m)?.[1]
      const raw = block.match(/^data:\s*(.+)$/m)?.[1]
      if (!event || !raw) continue
      const data = JSON.parse(raw) as Record<string, unknown>
      if (event === 'session') {
        mode = String(data.mode ?? 'rules')
        modeLabel = String(data.mode_label ?? '规则裁判')
        if (data.counts) counts = { ...counts, ...(data.counts as PanelCounts) }
      }
      if (event === 'message') {
        const message = data as unknown as PanelMessage
        messages.push(message)
        handlers.onMessage?.(message)
        if (message.agent === '裁判' && message.relation_id) {
          verdicts.push({
            relation_id: message.relation_id,
            status: message.status,
            verdict: message.status,
            judge_score: Number(message.confidence ?? 0),
            source: '',
            relation_type: '',
            target: '',
            confidence: Number(message.confidence ?? 0),
            evidence_count: 0,
            paper_id: message.paper_id,
          })
        }
      }
      if (event === 'summary' && data.counts) {
        counts = { ...counts, ...(data.counts as PanelCounts) }
      }
      if (event === 'error') throw new Error(String(data.message ?? '组会中断'))
    }
    if (done) break
  }
  return { mode, mode_label: modeLabel, messages, verdicts, counts }
}

/** 把组会结论写进项目：采纳的记 include，备注里写明是 AI 组会采纳的。 */
export function commitPanel(
  projectId: string,
  payload: {
    decisions: Array<{
      relation_id: string
      decision: 'include' | 'defer' | 'exclude'
      mode_label: string
    }>
  },
): Promise<{ written: number; relation_ids: string[] }> {
  return request(`/api/projects/${encodeURIComponent(projectId)}/panel/commit`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  })
}
