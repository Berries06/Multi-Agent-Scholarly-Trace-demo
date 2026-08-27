export interface Health {
  status: string
  service: string
  domain_count: number
  profile_count: number
  core_agents: number
  system_agents: number
}

// —— LLM 供应商配置 ——

export interface ProviderInfo {
  id: string
  label: string
  default_model: string
  models: string[]
  requires_api_key: boolean
  protocol: string
  available?: boolean
}

export interface LlmConfig {
  provider: string
  model?: string
  api_key?: string
  timeout_seconds?: number
}

export interface ProviderTestResult {
  ok: boolean
  provider: string
  model: string
  message?: string
  duration_ms?: number
  usage?: Record<string, number>
}

export interface LearnerProfile {
  profile_id: string
  name: string
  persona: string
  education: string
  role: string
  goal: string
  interests: string[]
  knowledge_scores: Record<string, number>
  preferred_style: string
  expected_difficulty: number
  synthetic: boolean
}

export interface Domain {
  domain_id: string
  domain_name: string
  paper_count: number
  evidence_paper_count: number
  metadata_only_paper_count: number
  query_example?: string
  description?: string
  [key: string]: unknown
}

export interface ExperimentProtocol {
  slug: string
  title: string
  purpose: string
  mode: string
  evaluation_type: string
  claim_ceiling: string
  primary_metrics: string[]
  config_path: string
}

export interface ExperimentRun {
  run_id: string
  artifact_path: string
  experiment: string
  title: string
  generated_at: string | null
  status: string
  evaluation_type: string
  claim_ceiling: string
  git_head: string | null
  git_dirty: boolean | null
  summary: Array<Record<string, unknown>>
  error?: string
}

export interface ExperimentLedger {
  schema_version: string
  protocol_count: number
  run_count: number
  run_command: string
  mlflow_url: string
  protocols: ExperimentProtocol[]
  runs: ExperimentRun[]
}

export interface AgentTraceStep {
  agent: string
  role: string
  status: string
  summary: string
  duration_ms?: number
  details?: Record<string, unknown>
}

export interface Diagnosis {
  readiness_score: number
  blind_spots: string[]
  strengths: string[]
  target_difficulty: number
  resource_match_score: number
  difficulty_curve: Array<{ stage: string; difficulty: number }>
  learning_path: string[]
}

export interface Claim {
  claim_id: string
  source: string
  relation: string
  target: string
  relation_type: string
  status: string
  judge_score: number
  criticisms: string[]
  evidence_ids: string[]
}

export interface Resources {
  briefing: {
    title: string
    level: number
    strategy: string
    sections: unknown[]
    citations: string[]
  }
  practical_guide: { title: string; estimated_minutes: number; steps: unknown[] }
  quiz: { title: string; items: unknown[] }
  blue_ocean: { hypothesis: string; caveat: string; evidence_ids: string[] }
  covered_concepts: string[]
}

export interface RunResult {
  run_id?: string
  profile: LearnerProfile
  diagnosis: Diagnosis
  agent_trace: AgentTraceStep[]
  specialist_agent_trace: AgentTraceStep[]
  claims: Claim[]
  resources: Resources
  metrics: {
    hallucination_proxy_rate: number
    adaptation_accuracy: number
    knowledge_coverage_rate: number
    accepted_claims: number
    rejected_claims: number
  }
  report: {
    blind_spots: string[]
    difficulty_curve: unknown[]
    learning_path: string[]
    resource_match_score: number
  }
  evidence_details?: Record<string, EvidenceSpan[]>
  ablation?: { variants: unknown[] }
  decision_layer?: {
    mode: string
    provider: Record<string, unknown> | null
    usage: Record<string, number>
  }
  provider_run?: Record<string, unknown>
}

// —— 实验台（粘贴论文）返回结构 ——

export interface EntityMention {
  mention_id: string
  entity_id: string
  surface_form: string
  evidence_id: string
  char_start: number
  char_end: number
}

export interface ExtractedEntity {
  entity_id: string
  canonical_name: string
  entity_type: string
  aliases: string[]
  mentions: EntityMention[]
  confidence: number
}

export interface ExtractedRelation {
  relation_id: string
  source_id: string
  target_id: string
  relation_type: string
  evidence_ids: string[]
  confidence: number
  status: string
  criticisms: string[]
  extraction_method: string
}

export interface EvidenceSpan {
  evidence_id: string
  paper_id: string
  section_id: string
  sentence_index: number
  text: string
  char_start: number
  char_end: number
}

export interface ExtractionResult {
  schema_version: string
  papers: unknown[]
  entities: ExtractedEntity[]
  relations: ExtractedRelation[]
  evidence: EvidenceSpan[]
  communities: unknown[]
  audit: Record<string, unknown>
  graph: { nodes: unknown[]; edges: unknown[] }
}

export interface DecisionClaim {
  claim_id: string
  source: string
  relation: string
  target: string
  relation_type: string
  base_confidence: number
  source_type: string
  target_type: string
  evidence_ids: string[]
  criticisms: string[]
  proposal_reason: string
  judge_reason: string
  judge_score: number
  status: string
}

export interface IngestSummary {
  entity_count: number
  candidate_relation_count: number
  claim_count: number
  accepted_count: number
  rejected_count: number
  needs_review_count: number
  accepted_without_evidence_count: number
}

export interface IngestResult {
  fingerprint: {
    paper_id: string
    title: string
    text_char_count: number
    accept_threshold: number
    profile_id: string
    schema_version: string
  }
  document: { paper_id: string; title: string; sections: Record<string, string> }
  extraction: ExtractionResult
  diagnosis: Diagnosis
  proposed_claims: DecisionClaim[]
  critiqued_claims: DecisionClaim[]
  adjudicated_claims: DecisionClaim[]
  agent_trace: AgentTraceStep[]
  specialist_agent_trace: AgentTraceStep[]
  resources: Resources
  summary: IngestSummary
  decision_layer?: {
    mode: string
    provider: Record<string, unknown> | null
    usage: Record<string, number>
  }
}

// —— 证据知识图谱（/api/extracted-graph）——

export interface GraphNode {
  id: string
  label: string
  kind: string
  confidence?: number
  source_url?: string
  paper_id?: string
  section_id?: string
  char_start?: number
  char_end?: number
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  label: string
  status?: string
  confidence?: number
  evidence_ids?: string[]
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

// —— 证据图谱工作区（/api/atlas）——

export interface AtlasDomainSummary {
  domain_id: string
  domain_name: string
  description: string
  query_example: string
  paper_count: number
  evidence_paper_count: number
  metadata_only_count: number
  entity_count: number
  relation_count: number
}

export interface AtlasPaper {
  paper_id: string
  title: string
  authors: string[]
  year: number
  venue: string
  doi: string
  source_url: string
  citation_count: number
  evidence_tier: 'evidence_card' | 'metadata_only'
  summary: string
  concepts: string[]
}

export interface AtlasEntity {
  entity_id: string
  canonical_name: string
  entity_type: string
  confidence: number
  mention_count: number
  aliases: string[]
}

export interface AtlasRelation {
  relation_id: string
  source_id: string
  target_id: string
  source_name: string
  target_name: string
  source_type: string
  target_type: string
  relation_type: string
  confidence: number
  status: string
  evidence_ids: string[]
}

export interface AtlasEvidence {
  evidence_id: string
  paper_id: string
  section_id: string
  text: string
  char_start: number
  char_end: number
}

export interface AtlasDomainData {
  domain_id: string
  domain_name: string
  description: string
  query_example: string
  papers: AtlasPaper[]
  entities: AtlasEntity[]
  relations: AtlasRelation[]
  evidence: AtlasEvidence[]
  paper_entities: Record<string, string[]>
  cards: Record<string, string>
}
