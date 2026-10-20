/**
 * 图谱配色的唯一来源。
 *
 * 原来这两份色板在 AtlasPage.tsx 和 AtlasGraph.tsx 里各写了一遍，atlas.css 里
 * 还有 8 个 `--c-*` 变量只有定义、零引用。改一次颜色要改三个地方，很容易漏。
 * ECharts 取色要的是 JS 里的值（每处读 CSS 变量都要 getComputedStyle，会拖慢
 * 图表重建），所以真源放在这个常量文件里，样式表那边需要颜色的地方改用类名。
 */

/** 实体类型 → 颜色（与 atlas.css 里图例点的类名一一对应） */
export const TYPE_COLORS: Record<string, string> = {
  METHOD: '#a51931',
  TASK: '#1f4e79',
  DATASET: '#2d6a4f',
  METRIC: '#b8860b',
  FINDING: '#c0531e',
  LIMITATION: '#7a756d',
  DOMAIN: '#6b4c8a',
  PAPER: '#2b2620',
}

/** 关系类型 → 颜色 */
export const REL_COLORS: Record<string, string> = {
  IMPROVES: '#2d6a4f',
  ENABLES: '#1f4e79',
  USES: '#8b8680',
  EVALUATES_ON: '#2a7b8c',
  REPORTS: '#b8860b',
  SUPPORTS: '#2d6a4f',
  CONTRADICTS: '#c0392b',
  EXTENDS: '#a51931',
  ADDRESSES: '#6b4c8a',
  BENCHMARKS: '#2a7b8c',
  RELATED_TO: '#cfc8bc',
}

/** 关系类型没有配色时用的兜底色（浅灰，和 RELATED_TO 同档） */
export const REL_FALLBACK_COLOR = '#cfc8bc'

/** 实体类型没有配色时用的兜底色 */
export const TYPE_FALLBACK_COLOR = '#999999'
