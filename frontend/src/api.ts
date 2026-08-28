import type {
  AgentTraceStep,
  AtlasDomainData,
  AtlasDomainSummary,
  AuthState,
  Domain,
  ExperimentLedger,
  GraphData,
  Health,
  IngestResult,
  LearnerProfile,
  LlmConfig,
  ProviderInfo,
  ProviderTestResult,
  RunResult,
  UserAccount,
} from './types'

const jsonHeaders = { 'Content-Type': 'application/json; charset=utf-8' }
const apiPrefix = window.location.pathname.startsWith('/AgentDemo/start') ? '/AgentDemo/start/api' : '/api'
const apiPath = (path: string) => path.replace(/^\/api/, apiPrefix)

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiPath(path), { credentials: 'include', ...init })
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { error?: { message?: string } } | null
    throw new Error(payload?.error?.message || `${response.status} ${response.statusText}`)
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

export function getExtractedGraph(domainId?: string | null): Promise<GraphData> {
  const suffix = domainId ? `?domain_id=${encodeURIComponent(domainId)}` : ''
  return request<GraphData | { graph: GraphData }>(`/api/extracted-graph${suffix}`)
    .then((payload) => ('graph' in payload ? payload.graph : payload))
}

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
}

export const runPipeline = (payload: RunPayload): Promise<RunResult> =>
  request('/api/run', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload) })

export async function streamPipeline(
  payload: RunPayload,
  handlers: { onStarted?: (operationId: string) => void; onStep?: (step: AgentTraceStep) => void },
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
      if (event === 'error') throw new Error(String(data.message ?? '运行中断'))
      if (event === 'completed') result = data.result as RunResult
    }
    if (done) break
  }
  if (!result) throw new Error('运行流已结束，但没有收到完成结果。')
  return result
}

export const sendFeedback = (payload: {
  profile_id: string; query: string; domain_id?: string | null; feedback: 'too_hard' | 'suitable' | 'too_easy'
}): Promise<RunResult> => request('/api/feedback', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload) })

export const searchOnline = (payload: { query: string; limit?: number; allow_network: boolean }): Promise<Record<string, unknown>> =>
  request('/api/online-rag', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload) })

export const queryGraph = (payload: { query: string; domain_id?: string | null }): Promise<Record<string, unknown>> =>
  request('/api/graph-query', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload) })

export interface IngestPayload {
  paper_id: string
  title: string
  text: string
  profile_id: string
  accept_threshold: number
  llm?: LlmConfig | null
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
}): Promise<IngestResult> {
  const form = new FormData()
  form.append('file', payload.file)
  form.append('profile_id', payload.profile_id)
  form.append('paper_id', payload.paper_id)
  form.append('title', payload.title)
  form.append('accept_threshold', String(payload.accept_threshold))
  if (payload.llm) form.append('llm', JSON.stringify(payload.llm))
  return request('/api/ingest-pdf', { method: 'POST', body: form })
}

export function getAtlasDomains(): Promise<{ domains: AtlasDomainSummary[] }> {
  return request('/api/atlas/domains')
}

export function getAtlasDomain(domainId: string): Promise<AtlasDomainData> {
  return request(`/api/atlas/${encodeURIComponent(domainId)}`)
}
