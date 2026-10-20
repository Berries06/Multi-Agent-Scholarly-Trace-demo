/** Display existing relation statuses without changing or filtering the data. */
export function relationStatusStyle(status?: string, relationLabel?: string): {
  label: string
  color?: string
  lineType: 'solid' | 'dashed' | 'dotted'
} {
  if (!status && ['CONTAINS', 'MENTIONS'].includes(relationLabel?.toUpperCase() ?? '')) {
    return { label: '结构关系', lineType: 'solid' }
  }
  if (status === 'accepted') return { label: '已接受', lineType: 'solid' }
  if (status === 'review' || status === 'needs_review') {
    return { label: '待复核', color: '#ad7627', lineType: 'dotted' }
  }
  if (status === 'rejected') return { label: '已拒绝', color: '#b21f2d', lineType: 'dashed' }
  const labels: Record<string, string> = {
    proposed: '候选', candidate: '候选', abstained: '未生成结论', superseded: '已替换',
  }
  return {
    label: status ? labels[status] ?? `未确认（${status}）` : '状态未提供',
    color: '#77746d',
    lineType: 'dotted',
  }
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character]!)
}

export function relationTooltip(label: string, status?: string): string {
  const display = relationStatusStyle(status, label)
  const detail = display.label === '结构关系'
    ? '说明：文档结构关系，不作结论判定'
    : `状态：${escapeHtml(display.label)}`
  return `关系：${escapeHtml(label)}<br/>${detail}`
}
