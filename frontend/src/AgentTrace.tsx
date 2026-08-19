import { Tag, Timeline, Typography } from 'antd'
import type { AgentTraceStep } from './types'

const { Text } = Typography

function statusColor(status: string): string {
  if (status === 'completed') return 'green'
  if (status === 'failed') return 'red'
  return 'blue'
}

export default function AgentTrace({ steps }: { steps: AgentTraceStep[] }) {
  const items = steps.map((step) => ({
    color: statusColor(step.status),
    children: (
      <div>
        <Text strong>{step.agent}</Text>
        <Tag style={{ marginLeft: 8 }} color={statusColor(step.status)}>
          {step.role}
        </Tag>
        <div style={{ color: '#666', marginTop: 4 }}>{step.summary}</div>
      </div>
    ),
  }))
  return <Timeline items={items} />
}
