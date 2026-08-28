import { BookOutlined, BulbOutlined, ExperimentOutlined, QuestionCircleOutlined } from '@ant-design/icons'
import { Collapse, List, Space, Tag, Typography } from 'antd'
import type { Resources } from './types'

const { Paragraph, Text } = Typography

function records(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object') : []
}

export default function ResourceSummary({ resources }: { resources: Resources }) {
  const steps = records(resources.practical_guide.steps)
  const questions = records(resources.quiz.items)
  return (
    <Collapse
      items={[
        {
          key: 'briefing',
          label: <Space><BookOutlined />导读</Space>,
          children: <><Text strong>{resources.briefing.title}</Text><Paragraph>{resources.briefing.strategy}</Paragraph></>,
        },
        {
          key: 'guide',
          label: <Space><ExperimentOutlined />实操 · {steps.length} 步</Space>,
          children: <List size="small" dataSource={steps} renderItem={(step, index) => <List.Item><List.Item.Meta title={`${index + 1}. ${String(step.title ?? '步骤')}`} description={String(step.action ?? '')} /></List.Item>} />,
        },
        {
          key: 'quiz',
          label: <Space><QuestionCircleOutlined />测评 · {questions.length} 题</Space>,
          children: <List size="small" dataSource={questions} renderItem={(item, index) => <List.Item>{index + 1}. {String(item.question ?? '理解检查')}</List.Item>} />,
        },
        {
          key: 'idea',
          label: <Space><BulbOutlined />研究 Idea <Tag color="gold">待验证</Tag></Space>,
          children: <><Paragraph>{resources.blue_ocean.hypothesis}</Paragraph><Text type="secondary">{resources.blue_ocean.caveat}</Text></>,
        },
      ]}
    />
  )
}
