import { useMemo } from 'react'
import ReactEChartsCore from 'echarts-for-react/lib/core'
import { echarts } from './echarts'
import type { GraphData } from './types'

const KIND_COLORS: Record<string, string> = {
  paper: '#262521',
  evidence: '#3f725d',
  method: '#ad7627',
  task: '#a31d29',
  dataset: '#57777b',
  metric: '#7e667b',
  finding: '#bd5a50',
  limitation: '#77746d',
  domain: '#5d766a',
  concept: '#665f58',
  outcome: '#4f6a78',
  evidence_span: '#3f725d',
}

const KIND_LABELS: Record<string, string> = {
  paper: '论文',
  evidence: '证据跨度',
  method: '方法',
  task: '任务',
  dataset: '数据集',
  metric: '指标',
  finding: '发现',
  limitation: '局限',
  domain: '领域',
  concept: '概念',
  outcome: '结论',
  evidence_span: '证据跨度',
}

function shorten(text: string, limit = 14): string {
  return text.length > limit ? `${text.slice(0, limit)}…` : text
}

export default function KnowledgeGraphView({ data }: { data: GraphData }) {
  const option = useMemo(() => {
    const kinds = Array.from(new Set(data.nodes.map((node) => node.kind)))
    const categories = kinds.map((kind) => ({
      name: KIND_LABELS[kind] ?? kind,
      itemStyle: { color: KIND_COLORS[kind] ?? '#94a3b8' },
    }))
    const nodeInfo = new Map(data.nodes.map((node) => [node.id, node]))
    const nodes = data.nodes.map((node) => ({
      id: node.id,
      name: shorten(node.label, 16),
      category: kinds.indexOf(node.kind),
      symbolSize: node.kind === 'paper' ? 36 : node.kind === 'evidence' ? 14 : 24,
    }))
    const links = data.edges.map((edge) => {
      const rejected = edge.status === 'rejected'
      return {
        source: edge.source,
        target: edge.target,
        lineStyle: {
          color: rejected ? '#b21f2d' : edge.label === 'MENTIONS' || edge.label === 'CONTAINS' ? '#d1ccc2' : '#8e8a82',
          width: rejected ? 2 : 1,
          type: rejected ? 'dashed' : 'solid',
        },
      }
    })
    return {
      tooltip: {
        formatter: (params: { dataType?: string; data?: { id?: string }; dataIndex?: number }) => {
          if (params.dataType === 'edge') return '关系边'
          const id = params.data?.id
          if (!id) return ''
          const node = nodeInfo.get(id)
          if (!node) return ''
          const detail = node.kind === 'evidence'
            ? `\n章节 ${node.section_id ?? '-'} · 字符 [${node.char_start}, ${node.char_end})`
            : node.source_url
              ? `\n来源 ${node.source_url}`
              : ''
          return `<b>${node.label}</b>\n类型：${KIND_LABELS[node.kind] ?? node.kind}${detail}`
        },
      },
      legend: [{ data: categories.map((category) => category.name), top: 0 }],
      series: [
        {
          type: 'graph',
          layout: 'force',
          roam: true,
          draggable: true,
          categories,
          data: nodes,
          links,
          label: { show: true, fontSize: 10, color: '#34322d' },
          force: { repulsion: 220, edgeLength: [50, 140], gravity: 0.08 },
          emphasis: { focus: 'adjacency', lineStyle: { width: 3 } },
          lineStyle: { opacity: 0.6 },
        },
      ],
    }
  }, [data])

  return (
    <ReactEChartsCore
      echarts={echarts}
      option={option}
      style={{ height: 560, width: '100%' }}
      notMerge
      opts={{ renderer: 'canvas' }}
    />
  )
}
