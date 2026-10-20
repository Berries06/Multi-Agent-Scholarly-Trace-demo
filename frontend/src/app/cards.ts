/**
 * 知识卡解析。
 *
 * 后端 `/api/atlas/{domain_id}` 的 `cards` 字段给的是
 * `data/vertical_kb/domains/<领域>/documents/<paper>.md` 的前 4000 个字符，
 * 结构固定为「一级标题 + 若干二级小标题 + 每个小标题下的句子」，例如：
 *
 *   # MEGNet
 *   ## Method
 *   MEGNet uses graph neural network.
 *   ## Evaluation
 *   MEGNet evaluates on Materials Project.
 *   ## Provenance
 *   本卡片为课题组依据 DOI ... 所作释义，不是论文全文逐字摘录。
 *
 * 这里只做结构切分，不推断、不补全、不改写任何一句正文。
 * 解析不出来就返回空，由调用方显示「这篇没有知识卡」，不拿别的数据拼一张卡。
 */

export interface CardSection {
  heading: string
  lines: string[]
}

export interface ParsedKnowledgeCard {
  /** 卡片自己的一级标题；通常与论文标题相同，取不到就为空串。 */
  title: string
  /** 正文小标题段落，按原文顺序。 */
  sections: CardSection[]
  /** 出处/版权说明：单独放，进卡片脚注，不和正文混在一个格子里。 */
  provenance: string
}

const PROVENANCE_HEADS = new Set([
  'provenance',
  'provance',
  '出处',
  '来源',
  '版权',
  '说明',
  '授权',
  'attribution',
  'license',
])

/** 小标题的中文对照。只为好读，不改变正文；对照表里没有的就原样显示。 */
const HEAD_LABELS: Record<string, string> = {
  method: '方法',
  approach: '方法',
  problem: '问题',
  question: '问题',
  motivation: '动机',
  background: '背景',
  evaluation: '评测',
  experiment: '实验',
  experiments: '实验',
  dataset: '数据集',
  datasets: '数据集',
  benchmark: '基准',
  finding: '发现',
  findings: '发现',
  result: '结果',
  results: '结果',
  conclusion: '结论',
  contribution: '贡献',
  contributions: '贡献',
  limitation: '局限',
  limitations: '局限',
}

function normalizeHeading(heading: string): string {
  return heading.trim().toLowerCase().replace(/[：:]\s*$/, '')
}

export function isProvenanceHeading(heading: string): boolean {
  return PROVENANCE_HEADS.has(normalizeHeading(heading))
}

export function headingLabel(heading: string): string {
  return HEAD_LABELS[normalizeHeading(heading)] ?? heading.trim()
}

export function parseKnowledgeCard(markdown: string): ParsedKnowledgeCard {
  const result: ParsedKnowledgeCard = { title: '', sections: [], provenance: '' }
  if (!markdown || !markdown.trim()) return result

  const provenance: string[] = []
  let current: CardSection | null = null
  let inProvenance = false

  for (const raw of markdown.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line) continue

    const h1 = /^#\s+(.+)$/.exec(line)
    if (h1) {
      if (!result.title) result.title = h1[1].trim()
      current = null
      inProvenance = false
      continue
    }

    const h2 = /^#{2,6}\s+(.+)$/.exec(line)
    if (h2) {
      const heading = h2[1].trim()
      if (isProvenanceHeading(heading)) {
        current = null
        inProvenance = true
      } else {
        current = { heading, lines: [] }
        result.sections.push(current)
        inProvenance = false
      }
      continue
    }

    if (inProvenance) provenance.push(line)
    else if (current) current.lines.push(line)
    // 既没有小标题也不在出处段的游离行：丢弃，不猜它属于哪一节
  }

  result.provenance = provenance.join(' ').replace(/\s+/g, ' ').trim()
  result.sections = result.sections.filter((section) => section.lines.length > 0)
  return result
}

/** 把一个小标题下的多行正文合成一句可渲染的文本，不改写内容。 */
export function sectionText(section: CardSection): string {
  return section.lines.join(' ').replace(/\s+/g, ' ').trim()
}
