import { Steps } from 'antd'
import type { AgentTraceStep } from './types'

interface Props {
  steps: AgentTraceStep[]
}

function stepStatus(status: string): 'finish' | 'process' | 'error' {
  if (status === 'completed') return 'finish'
  if (status === 'failed') return 'error'
  return 'process'
}

export default function AgentTrace({ steps }: Props) {
  const items = steps.map((step) => ({
    title: `${step.agent} · ${step.role}`,
    description: step.summary,
    status: stepStatus(step.status),
  }))
  return <Steps direction="vertical" size="small" items={items} />
}
