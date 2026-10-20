import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

// Compile only the pure display helper with the project's existing TypeScript dependency.
const source = await readFile(new URL('../src/graphStatus.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext },
}).outputText
const { relationStatusStyle, relationTooltip } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`
)

test('both review status names have the same distinct appearance', () => {
  const review = relationStatusStyle('review')
  assert.deepEqual(review, relationStatusStyle('needs_review'))
  assert.equal(review.label, '待复核')
  assert.equal(review.lineType, 'dotted')
  assert.ok(review.color)
  assert.notEqual(review.lineType, relationStatusStyle('accepted').lineType)
})

test('accepted relations retain their normal solid line and relation color', () => {
  assert.deepEqual(relationStatusStyle('accepted'), { label: '已接受', lineType: 'solid' })
})

test('rejected relations remain explicitly rejected', () => {
  const style = relationStatusStyle('rejected')
  assert.equal(style.label, '已拒绝')
  assert.equal(style.lineType, 'dashed')
  assert.notEqual(style.color, relationStatusStyle('review').color)
})

test('missing and unknown status values are not labelled accepted', () => {
  assert.equal(relationStatusStyle().label, '状态未提供')
  assert.equal(relationStatusStyle('new-status').label, '未确认（new-status）')
  assert.equal(relationStatusStyle('proposed').label, '候选')
})

test('structural edges without a verdict retain their existing solid line and color', () => {
  for (const relation of ['CONTAINS', 'MENTIONS']) {
    assert.deepEqual(relationStatusStyle(undefined, relation), {
      label: '结构关系', lineType: 'solid',
    })
  }
})

test('structural tooltips explain that the edge is not a research conclusion', () => {
  assert.equal(relationTooltip('CONTAINS'), '关系：CONTAINS<br/>说明：文档结构关系，不作结论判定')
})

test('an explicit verdict on a structural label is still displayed', () => {
  assert.equal(relationStatusStyle('review', 'CONTAINS').label, '待复核')
  assert.equal(relationStatusStyle('review', 'CONTAINS').lineType, 'dotted')
})

test('edge tooltips include both the relation and its review status', () => {
  assert.equal(relationTooltip('SUPPORTS', 'needs_review'), '关系：SUPPORTS<br/>状态：待复核')
})

test('tooltip text is escaped before it is inserted into HTML', () => {
  const tooltip = relationTooltip('<img src=x onerror=alert(1)>', '<script>')
  assert.ok(!tooltip.includes('<img'))
  assert.ok(!tooltip.includes('<script>'))
  assert.ok(tooltip.includes('&lt;img'))
})
