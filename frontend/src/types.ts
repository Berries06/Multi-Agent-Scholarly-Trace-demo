export interface Health {
  status: string
  service: string
  domain_count: number
  profile_count: number
  core_agents: number
  system_agents: number
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

export interface RunResult {
  profile: LearnerProfile
  diagnosis: Diagnosis
  agent_trace: AgentTraceStep[]
  specialist_agent_trace: AgentTraceStep[]
  claims: Claim[]
  resources: {
    briefing: { title: string; level: number; strategy: string; sections: unknown[] }
    practical_guide: { title: string; steps: unknown[] }
    quiz: { title: string; items: unknown[] }
    blue_ocean: { hypothesis: string; caveat: string }
  }
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
  ablation?: { variants: unknown[] }
}
