import ReactEChartsCore from 'echarts-for-react/lib/core'
import { echarts } from './echarts'
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
  return <ReactEChartsCore echarts={echarts} option={option} style={{ height: 320 }} notMerge />
}
