import { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import type { GraphData } from './types'

const KIND_COLORS: Record<string, string> = {
  paper: '#4f46e5',
  evidence: '#16a34a',
  method: '#f59e0b',
  task: '#ef4444',
  dataset: '#06b6d4',
  metric: '#8b5cf6',
  finding: '#ec4899',
  limitation: '#64748b',
  domain: '#14b8a6',
  concept: '#6366f1',
  outcome: '#0ea5e9',
  evidence_span: '#16a34a',
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
          color: rejected ? '#ef4444' : edge.label === 'MENTIONS' || edge.label === 'CONTAINS' ? '#cbd5e1' : '#94a3b8',
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
          label: { show: true, fontSize: 10, color: '#334155' },
          force: { repulsion: 220, edgeLength: [50, 140], gravity: 0.08 },
          emphasis: { focus: 'adjacency', lineStyle: { width: 3 } },
          lineStyle: { opacity: 0.6 },
        },
      ],
    }
  }, [data])

  return (
    <ReactECharts
      option={option}
      style={{ height: 560, width: '100%' }}
      notMerge
      opts={{ renderer: 'canvas' }}
    />
  )
}
