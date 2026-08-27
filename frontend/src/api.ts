import type {
  AtlasDomainData,
  AtlasDomainSummary,
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
} from './types'

const jsonHeaders = { 'Content-Type': 'application/json' }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(`${response.status} ${response.statusText}: ${detail}`)
  }
  return response.json() as Promise<T>
}

export function getHealth(): Promise<Health> {
  return request('/api/health')
}

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

export interface RunPayload {
  profile_id: string
  query: string
  domain_id?: string | null
  include_ablation?: boolean
  llm?: LlmConfig | null
}

export function runPipeline(payload: RunPayload): Promise<RunResult> {
  return request('/api/run', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  })
}

export interface IngestPayload {
  paper_id: string
  title: string
  text: string
  profile_id: string
  accept_threshold: number
  llm?: LlmConfig | null
}

export function ingestPaper(payload: IngestPayload): Promise<IngestResult> {
  return request('/api/ingest-paper', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  })
}

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
