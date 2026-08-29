import { useMemo } from 'react'
import ReactEChartsCore from 'echarts-for-react/lib/core'
import { echarts } from '../echarts'
import type { AtlasDomainData } from '../types'

const TYPE_COLORS: Record<string, string> = {
  METHOD: '#a51931',
  TASK: '#1f4e79',
  DATASET: '#2d6a4f',
  METRIC: '#b8860b',
  FINDING: '#c0531e',
  LIMITATION: '#7a756d',
  DOMAIN: '#6b4c8a',
  PAPER: '#2b2620',
}

const REL_COLORS: Record<string, string> = {
  IMPROVES: '#2d6a4f', ENABLES: '#1f4e79', USES: '#8b8680',
  EVALUATES_ON: '#2a7b8c', REPORTS: '#b8860b', SUPPORTS: '#2d6a4f',
  CONTRADICTS: '#c0392b', EXTENDS: '#a51931', ADDRESSES: '#6b4c8a',
  BENCHMARKS: '#2a7b8c', RELATED_TO: '#cfc8bc',
}

interface Props {
  data: AtlasDomainData
  view: 'force' | 'timeline'
  hiddenTypes: Set<string>
  onSelectPaper: (id: string) => void
  onSelectEntity: (id: string) => void
}

export default function AtlasGraph({ data, view, hiddenTypes, onSelectPaper, onSelectEntity }: Props) {
  const option = useMemo(() => {
    if (view === 'timeline') return buildTimelineOption(data)
    return buildForceOption(data, hiddenTypes)
  }, [data, view, hiddenTypes])

  const onChartClick = (params: { data?: { id?: string; kind?: string } }) => {
    const id = params.data?.id
    if (!id) return
    if (params.data?.kind === 'paper') onSelectPaper(id)
    else if (params.data?.kind === 'entity') onSelectEntity(id)
  }

  return (
    <ReactEChartsCore
      echarts={echarts}
      option={option}
      style={{ height: '100%', width: '100%' }}
      notMerge
      onEvents={{ click: onChartClick }}
      opts={{ renderer: 'canvas' }}
    />
  )
}

function buildForceOption(data: AtlasDomainData, hiddenTypes: Set<string>) {
  const visible = data.entities.filter((e) => !hiddenTypes.has(e.entity_type))
  const visibleIds = new Set(visible.map((e) => e.entity_id))
  const maxMentions = Math.max(...visible.map((e) => e.mention_count), 1)

  const nodes = visible.map((e) => ({
    id: e.entity_id,
    name: e.canonical_name,
    kind: 'entity' as const,
    symbolSize: 14 + Math.sqrt(e.mention_count / maxMentions) * 22,
    label: { show: true, fontSize: 10, color: '#2b2620' },
    itemStyle: { color: TYPE_COLORS[e.entity_type] ?? '#999', borderColor: '#fff', borderWidth: 1.5 },
  }))

  const links = data.relations
    .filter((r) => visibleIds.has(r.source_id) && visibleIds.has(r.target_id))
    .map((r) => ({
      source: r.source_id,
      target: r.target_id,
      lineStyle: {
        color: r.status === 'rejected' ? '#c0392b' : REL_COLORS[r.relation_type] ?? '#cfc8bc',
        width: r.status === 'rejected' ? 1.5 : 1 + (r.confidence - 0.6) * 3,
        type: r.status === 'rejected' ? ('dashed' as const) : ('solid' as const),
        opacity: r.relation_type === 'RELATED_TO' ? 0.3 : 0.65,
        curveness: 0.08,
      },
    }))

  return {
    tooltip: {
      formatter: (p: { dataType?: string; data?: { id?: string } }) => {
        if (p.dataType === 'edge') return '关系'
        const e = data.entities.find((x) => x.entity_id === p.data?.id)
        if (!e) return ''
        return `<b>${e.canonical_name}</b><br/>类型: ${e.entity_type}<br/>提及: ${e.mention_count} 次<br/>置信度: ${(e.confidence * 100).toFixed(0)}%`
      },
    },
    animationDuration: 500,
    series: [{
      type: 'graph',
      layout: 'force',
      roam: true,
      draggable: true,
      data: nodes,
      links,
      force: { repulsion: 450, edgeLength: [80, 200], gravity: 0.04, friction: 0.6 },
      labelLayout: { hideOverlap: true },
      emphasis: { focus: 'adjacency', lineStyle: { width: 3 } },
      edgeSymbol: ['none', 'arrow'],
      edgeSymbolSize: [0, 7],
      zoom: 1.1,
    }],
  }
}

function buildTimelineOption(data: AtlasDomainData) {
  const papers = data.papers
  if (!papers.length) return { series: [] }
  const maxCites = Math.max(...papers.map((p) => p.citation_count), 1)
  const sizeScale = 26 / Math.sqrt(maxCites)

  const jitter = (seed: number) => {
    const x = Math.sin(seed * 99.13 + 7.7) * 10000
    return (x - Math.floor(x) - 0.5) * 0.6
  }

  const nodes = papers.map((p, i) => {
    const isEvidence = p.evidence_tier === 'evidence_card'
    return {
      id: p.paper_id,
      name: p.title.length > 40 ? p.title.slice(0, 40) + '…' : p.title,
      kind: 'paper' as const,
      value: [p.year + jitter(i), Math.max(1, p.citation_count)],
      symbolSize: Math.max(7, Math.sqrt(p.citation_count) * sizeScale + 4),
      itemStyle: {
        color: isEvidence ? 'rgba(45,106,79,.75)' : 'rgba(255,255,255,.85)',
        borderColor: isEvidence ? '#2d6a4f' : '#b8b0a4',
        borderWidth: isEvidence ? 1.5 : 1,
      },
      label: { show: false },
      emphasis: {
        label: { show: true, position: 'top', fontSize: 10, color: '#1a1815', fontWeight: 600 },
        itemStyle: { color: isEvidence ? '#2d6a4f' : '#fff', borderColor: '#a51931', borderWidth: 2.5 },
      },
    }
  })

  return {
    tooltip: {
      formatter: (p: { data?: { id?: string } }) => {
        const paper = data.papers.find((x) => x.paper_id === p.data?.id)
        if (!paper) return ''
        return `<b>${paper.title}</b><br/>${paper.venue} · ${paper.year}<br/>引用量: ${paper.citation_count}`
      },
    },
    grid: { left: 56, right: 24, top: 16, bottom: 36 },
    xAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { fontSize: 10, color: '#9a938a', formatter: (v: number) => Number.isInteger(v) ? v : '' },
      axisLine: { lineStyle: { color: '#c8c0b2' } },
      splitLine: { lineStyle: { color: '#ede8df', type: 'dashed' as const } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'log',
      axisLabel: {
        fontSize: 10, color: '#9a938a',
        formatter: (v: number) => v >= 1000 ? `${(v / 1000).toFixed(v >= 10000 ? 0 : 1)}k` : String(v),
      },
      axisLine: { show: false },
      splitLine: { lineStyle: { color: '#f2ede4' } },
      axisTick: { show: false },
      name: '引用量',
      nameLocation: 'middle', nameGap: 40, nameRotate: 90,
      nameTextStyle: { fontSize: 10, color: '#9a938a' },
    },
    series: [{
      type: 'scatter',
      data: nodes,
      emphasis: { focus: 'self', scale: 1.3 },
      z: 3,
    }],
    dataZoom: [
      { type: 'inside', xAxisIndex: 0, filterMode: 'none' },
      { type: 'inside', yAxisIndex: 0, filterMode: 'none' },
    ],
  }
}
