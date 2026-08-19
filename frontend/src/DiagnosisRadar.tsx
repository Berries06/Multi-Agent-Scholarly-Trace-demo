import ReactECharts from 'echarts-for-react'
import type { LearnerProfile } from './types'

interface Props {
  profile: LearnerProfile
}

export default function DiagnosisRadar({ profile }: Props) {
  const entries = Object.entries(profile.knowledge_scores)
  const option = {
    tooltip: {},
    radar: {
      indicator: entries.map(([name]) => ({ name, max: 100 })),
    },
    series: [
      {
        type: 'radar',
        data: [
          {
            value: entries.map(([, score]) => score),
            name: profile.name,
            areaStyle: { opacity: 0.2 },
          },
        ],
      },
    ],
  }
  return <ReactECharts option={option} style={{ height: 320 }} notMerge />
}
