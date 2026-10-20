import { useEffect, useState } from 'react'
import { getAtlasDomain, getAtlasDomains } from '../api'
import type { AtlasDomainData, AtlasDomainSummary } from '../types'

/**
 * 八个工作区：按 V3.1 用户端导航定的（2026-10-18 替换掉原来的六个）。
 * 内部实验与评测属于独立研海 Lab，不出现在这份导航里。
 */
export type Section =
  | 'overview'
  | 'workbench'
  | 'library'
  | 'build'
  | 'graph'
  | 'evidence'
  | 'findings'
  | 'settings'
  // 内部实验台：不出现在导航里，只能用 #/lab 直接打开。
  // 按 V3.1 的边界，消融、协议与跟踪属于独立研海 Lab，不该出现在终端科研用户的菜单里。
  | 'lab'

export interface SectionMeta {
  key: Section
  label: string
  hint: string
}

export const SECTIONS: SectionMeta[] = [
  { key: 'overview', label: '课题概览', hint: '研究问题、最近研究、图谱规模' },
  { key: 'workbench', label: '研究工作台', hint: '提问、看主张与证据' },
  { key: 'library', label: '文献库', hint: '导入论文、看来源与全文状态' },
  { key: 'build', label: '构建图谱', hint: '候选关系、原文、加入我的图谱' },
  { key: 'graph', label: '知识图谱', hint: '已纳入的关系与节点' },
  { key: 'evidence', label: '证据中心', hint: '逐条读原文、定位证据跨度' },
  { key: 'findings', label: '研究发现', hint: '本课题的结论与数据范围' },
  { key: 'settings', label: '设置', hint: '改名、导出、版本与保留授权' },
]

export const SECTION_GROUPS: Array<{ title: string; keys: Section[] }> = [
  { title: '研究课题', keys: ['overview', 'workbench', 'library', 'build', 'graph', 'evidence', 'findings'] },
  { title: '课题', keys: ['settings'] },
]

export const DEFAULT_SECTION: Section = 'overview'

const KEYS = new Set<string>(SECTIONS.map((item) => item.key))

/** 改版前的旧地址继续可用，不要让收藏的链接失效。 */
export const SECTION_ALIASES: Record<string, Section> = {
  dashboard: 'overview',
  research: 'workbench',
  product: 'workbench',
  atlas: 'graph',
  verify: 'evidence',
}

export function sectionFromHash(hash: string): Section {
  const cleaned = hash.replace(/^#\/?/, '').split('?')[0].trim().toLowerCase()
  // 内部实验台只认这一个地址，且不在导航里
  if (cleaned === 'lab' || cleaned === 'experiments') return 'lab'
  if (SECTION_ALIASES[cleaned]) return SECTION_ALIASES[cleaned]
  return KEYS.has(cleaned) ? (cleaned as Section) : DEFAULT_SECTION
}

export function hashFor(section: Section): string {
  return `#/${section}`
}

export function labelOf(section: Section): string {
  if (section === 'lab') return '研海 Lab（内部）'
  return SECTIONS.find((item) => item.key === section)?.label ?? '概览'
}

/** 领域与图谱数据的取数逻辑，文献库 / 图谱 / 核验三页共用一份。 */
export function useAtlasData() {
  const [domains, setDomains] = useState<AtlasDomainSummary[]>([])
  const [domainId, setDomainId] = useState('')
  const [data, setData] = useState<AtlasDomainData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let alive = true
    getAtlasDomains()
      .then((result) => {
        if (!alive) return
        setDomains(result.domains ?? [])
        setDomainId((current) => current || result.domains?.[0]?.domain_id || '')
      })
      .catch((err: Error) => { if (alive) setError(err.message) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [])

  useEffect(() => {
    if (!domainId) return
    let alive = true
    setLoading(true)
    getAtlasDomain(domainId)
      .then((result) => { if (alive) { setData(result); setError(null) } })
      .catch((err: Error) => { if (alive) setError(err.message) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [domainId])

  return { domains, domainId, setDomainId, data, loading, error }
}

/** 关系状态的中文与样式：机器判断只有三档，不冒充「已证实」。 */
export function statusText(status: string): { text: string; tone: string } {
  if (status === 'accepted') return { text: '系统接受候选', tone: 'tag--accepted' }
  if (status === 'needs_review') return { text: '需复核', tone: 'tag--review' }
  if (status === 'rejected') return { text: '已拒绝', tone: 'tag--rejected' }
  return { text: status || '未知', tone: '' }
}
