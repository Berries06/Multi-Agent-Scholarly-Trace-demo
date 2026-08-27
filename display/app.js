/* ============================================================
   研海寻踪 · 证据图谱  —  display prototype
   ============================================================ */

const COLORS = {
  METHOD:     '#a51931',
  TASK:       '#1f4e79',
  DATASET:    '#2d6a4f',
  METRIC:     '#b8860b',
  FINDING:    '#c0531e',
  LIMITATION: '#7a756d',
  DOMAIN:     '#6b4c8a',
  PAPER:      '#2b2620',
  EVIDENCE:   '#5a7d6f',
};
const TYPE_LABELS = {
  METHOD:'方法', TASK:'任务', DATASET:'数据集', METRIC:'指标',
  FINDING:'发现', LIMITATION:'局限', DOMAIN:'领域', PAPER:'论文',
};
const REL_COLORS = {
  IMPROVES:'#2d6a4f', ENABLES:'#1f4e79', USES:'#8b8680',
  EVALUATES_ON:'#2a7b8c', REPORTS:'#b8860b', SUPPORTS:'#2d6a4f',
  CONTRADICTS:'#c0392b', EXTENDS:'#a51931', ADDRESSES:'#6b4c8a',
  BENCHMARKS:'#2a7b8c', RELATED_TO:'#cfc8bc',
};
const REL_LABELS = {
  IMPROVES:'改善', ENABLES:'使能', USES:'使用', EVALUATES_ON:'评测于',
  REPORTS:'报告', SUPPORTS:'支持', CONTRADICTS:'矛盾', EXTENDS:'扩展',
  ADDRESSES:'针对', BENCHMARKS:'基准', RELATED_TO:'相关',
};

// ─── State ───
const state = {
  data: null,
  domainId: null,
  view: 'force',       // 'force' | 'timeline'
  search: '',
  yearMin: null,
  yearMax: null,
  sortBy: 'citation_desc',
  tiers: new Set(['evidence_card', 'metadata_only']),
  hiddenTypes: new Set(),
  selectedNode: null,
  chart: null,
};

// ─── Data loading ───
async function loadData() {
  const res = await fetch('data.json');
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ─── Domain tabs ───
function renderDomainTabs() {
  const tabs = document.getElementById('domainTabs');
  tabs.innerHTML = state.data.domains.map(d => `
    <button class="domain-tab ${d.domain_id === state.domainId ? 'is-active' : ''}"
            data-id="${d.domain_id}">
      <span class="domain-tab__name">${d.domain_name}</span>
      <span class="domain-tab__count">${d.paper_count} 篇 · ${d.entity_count} 实体 · ${d.relation_count} 关系</span>
    </button>
  `).join('');
  tabs.querySelectorAll('.domain-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      state.domainId = btn.dataset.id;
      state.selectedNode = null;
      state.search = '';
      document.getElementById('paperSearch').value = '';
      renderDomainTabs();
      renderAll();
    });
  });
}

function currentDomain() {
  return state.data.domains.find(d => d.domain_id === state.domainId);
}

// ─── Paper list ───
function filteredPapers() {
  const d = currentDomain();
  let list = d.papers.slice();
  if (state.search) {
    const q = state.search.toLowerCase();
    list = list.filter(p =>
      p.title.toLowerCase().includes(q) ||
      p.authors.some(a => a.toLowerCase().includes(q)) ||
      (p.concepts || []).some(c => c.toLowerCase().includes(q))
    );
  }
  if (state.yearMin) list = list.filter(p => p.year >= state.yearMin);
  if (state.yearMax) list = list.filter(p => p.year <= state.yearMax);
  list = list.filter(p => state.tiers.has(p.evidence_tier));
  const sorters = {
    citation_desc: (a,b) => b.citation_count - a.citation_count,
    citation_asc:  (a,b) => a.citation_count - b.citation_count,
    year_desc:     (a,b) => b.year - a.year || b.citation_count - a.citation_count,
    year_asc:      (a,b) => a.year - b.year || b.citation_count - a.citation_count,
    title_asc:     (a,b) => a.title.localeCompare(b.title),
  };
  list.sort(sorters[state.sortBy]);
  return list;
}

function renderPaperList() {
  const list = filteredPapers();
  const container = document.getElementById('paperList');
  container.innerHTML = list.map(p => `
    <div class="paper-item ${state.selectedNode?.kind === 'paper' && state.selectedNode.id === p.paper_id ? 'is-active' : ''}"
         data-id="${p.paper_id}">
      <div class="paper-item__title">${escapeHtml(p.title)}</div>
      <div class="paper-item__meta">
        <span class="tier-badge tier-badge--${p.evidence_tier === 'evidence_card' ? 'evidence' : 'metadata'}">
          ${p.evidence_tier === 'evidence_card' ? '证据卡' : '元数据'}
        </span>
        <span class="paper-item__venue">${escapeHtml(p.venue)}</span>
        <span class="paper-item__year">${p.year}</span>
        <span class="paper-item__cites">${p.citation_count} cites</span>
      </div>
    </div>
  `).join('');
  container.querySelectorAll('.paper-item').forEach(el => {
    el.addEventListener('click', () => selectPaper(el.dataset.id));
  });
}

// ─── Entity legend ───
function renderEntityLegend() {
  const d = currentDomain();
  const types = [...new Set(d.entities.map(e => e.entity_type))].sort();
  const el = document.getElementById('entityLegend');
  el.innerHTML = types.map(t => `
    <span class="legend-item ${state.hiddenTypes.has(t) ? 'is-off' : ''}" data-type="${t}">
      <span class="legend-dot" style="background:${COLORS[t] || '#999'}"></span>
      ${TYPE_LABELS[t] || t}
    </span>
  `).join('');
  el.querySelectorAll('.legend-item').forEach(item => {
    item.addEventListener('click', () => {
      const t = item.dataset.type;
      if (state.hiddenTypes.has(t)) state.hiddenTypes.delete(t);
      else state.hiddenTypes.add(t);
      renderEntityLegend();
      renderGraph();
    });
  });
}

// ─── ECharts graph ───
function renderGraph() {
  const d = currentDomain();
  const dom = document.getElementById('graphCanvas');
  if (!state.chart) state.chart = echarts.init(dom, null, { renderer: 'canvas' });

  const option = state.view === 'force'
    ? buildForceOption(d)
    : buildTimelineOption(d);

  state.chart.setOption(option, true);
  state.chart.off('click');
  state.chart.on('click', (params) => {
    const nodeId = params.data && params.data.id;
    if (!nodeId) return;
    if (params.data.kind === 'paper') selectPaper(nodeId);
    else if (params.data.kind === 'entity') selectEntity(nodeId);
  });

  // Update status
  const s0 = option.series[0];
  const nodeCount = s0.data ? s0.data.length : 0;
  const edgeCount = s0.links ? s0.links.length : 0;
  document.getElementById('statusNodes').textContent = `节点 ${nodeCount}`;
  document.getElementById('statusEdges').textContent = `关系 ${edgeCount}`;
  document.getElementById('statusEvidence').textContent = `证据跨度 ${d.evidence.length}`;
}

function buildForceOption(d) {
  const visibleEntities = d.entities.filter(e => !state.hiddenTypes.has(e.entity_type));
  const visibleIds = new Set(visibleEntities.map(e => e.entity_id));

  // Count evidence per entity for sizing
  const mentionCount = {};
  visibleEntities.forEach(e => { mentionCount[e.entity_id] = e.mention_count || 1; });
  const maxMentions = Math.max(...Object.values(mentionCount), 1);

  const nodes = visibleEntities.map(e => ({
    id: e.entity_id,
    name: e.canonical_name,
    kind: 'entity',
    entityType: e.entity_type,
    symbolSize: 14 + Math.sqrt(e.mention_count / maxMentions) * 22,
    label: { show: true, fontSize: 10, color: '#2b2620' },
    itemStyle: {
      color: COLORS[e.entity_type] || '#999',
      borderColor: '#fff', borderWidth: 1.5,
    },
    emphasis: { itemStyle: { borderColor: COLORS[e.entity_type], borderWidth: 2.5 } },
  }));

  const links = d.relations
    .filter(r => visibleIds.has(r.source_id) && visibleIds.has(r.target_id))
    .map(r => ({
      source: r.source_id,
      target: r.target_id,
      relationType: r.relation_type,
      status: r.status,
      confidence: r.confidence,
      lineStyle: {
        color: r.status === 'rejected' ? '#c0392b' : (REL_COLORS[r.relation_type] || '#cfc8bc'),
        width: r.status === 'rejected' ? 1.5 : 1 + (r.confidence - 0.6) * 3,
        type: r.status === 'rejected' ? 'dashed' : 'solid',
        opacity: r.relation_type === 'RELATED_TO' ? 0.35 : 0.7,
        curveness: 0.08,
      },
      label: {
        show: false,
        formatter: REL_LABELS[r.relation_type] || r.relation_type,
        fontSize: 9, color: REL_COLORS[r.relation_type] || '#999',
        backgroundColor: 'rgba(255,255,255,.85)', padding: [1,3], borderRadius: 2,
      },
    }));

  // Build categories for legend
  const types = [...new Set(visibleEntities.map(e => e.entity_type))];
  const categories = types.map(t => ({
    name: TYPE_LABELS[t] || t,
    itemStyle: { color: COLORS[t] || '#999' },
  }));

  return {
    tooltip: {
      formatter: (p) => {
        if (p.dataType === 'edge') {
          const r = d.relations.find(x =>
            x.source_id === p.data.source && x.target_id === p.data.target
            && x.relation_type === p.data.relationType);
          if (!r) return '关系';
          return `<b>${escapeHtml(r.source_name)}</b> → ${REL_LABELS[r.relation_type] || r.relation_type} → <b>${escapeHtml(r.target_name)}</b><br/>`
            + `置信度: ${(r.confidence*100).toFixed(0)}% · 证据: ${r.evidence_ids.length} 条<br/>`
            + `状态: ${r.status === 'rejected' ? '已拒绝' : '已接受'}`;
        }
        const e = d.entities.find(x => x.entity_id === p.data.id);
        if (!e) return '';
        const paperCount = (d.paper_entities && countPapersForEntity(d, e.entity_id)) || 0;
        return `<b>${escapeHtml(e.canonical_name)}</b><br/>`
          + `类型: ${TYPE_LABELS[e.entity_type] || e.entity_type}<br/>`
          + `提及: ${e.mention_count} 次 · 涉及论文: ${paperCount} 篇<br/>`
          + `置信度: ${(e.confidence*100).toFixed(0)}%`;
      },
    },
    animationDuration: 600,
    series: [{
      type: 'graph',
      layout: 'force',
      roam: true,
      draggable: true,
      categories,
      data: nodes,
      links,
      force: {
        repulsion: 480,
        edgeLength: [80, 200],
        gravity: 0.04,
        friction: 0.6,
        layoutAnimation: false,
      },
      labelLayout: { hideOverlap: true },
      emphasis: {
        focus: 'adjacency',
        lineStyle: { width: 3 },
        label: { show: true, fontWeight: 700 },
      },
      lineStyle: { opacity: 0.6 },
      zoom: 1.1,
      edgeSymbol: ['none', 'arrow'],
      edgeSymbolSize: [0, 7],
    }],
  };
}

function buildTimelineOption(d) {
  const papers = filteredPapers();
  if (!papers.length) return emptyGraphOption('无符合筛选条件的论文');

  const maxCites = Math.max(...papers.map(p => p.citation_count), 1);
  const years = papers.map(p => p.year);
  const yMin = Math.min(...years) - 1;
  const yMax = Math.max(...years) + 1;
  const sizeScale = 26 / Math.sqrt(maxCites);

  // Deterministic jitter so same-year papers don't perfectly overlap
  function jitter(seed) {
    const x = Math.sin(seed * 99.13 + 7.7) * 10000;
    return (x - Math.floor(x) - 0.5) * 0.6;
  }

  const nodes = papers.map((p, i) => {
    const isEvidence = p.evidence_tier === 'evidence_card';
    return {
      id: p.paper_id,
      name: p.title.length > 40 ? p.title.slice(0, 40) + '…' : p.title,
      kind: 'paper',
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
    };
  });

  return {
    tooltip: {
      formatter: (p) => {
        const paper = d.papers.find(x => x.paper_id === p.data.id);
        if (!paper) return '';
        return `<b>${escapeHtml(paper.title)}</b><br/>`
          + `${escapeHtml(paper.venue)} · ${paper.year}<br/>`
          + `引用量: ${paper.citation_count} · ${paper.evidence_tier === 'evidence_card' ? '含证据卡' : '仅元数据'}`;
      },
    },
    grid: { left: 56, right: 24, top: 16, bottom: 36 },
    xAxis: {
      type: 'value',
      min: yMin, max: yMax,
      minInterval: 1,
      axisLabel: { fontSize: 10, color: '#9a938a', formatter: v => Number.isInteger(v) ? v : '' },
      axisLine: { lineStyle: { color: '#c8c0b2' } },
      splitLine: { show: true, lineStyle: { color: '#ede8df', type: 'dashed' } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'log',
      logBase: 10,
      axisLabel: {
        fontSize: 10, color: '#9a938a',
        formatter: v => v >= 1000 ? (v / 1000).toFixed(v >= 10000 ? 0 : 1) + 'k' : v,
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
      coordinateSystem: 'cartesian2d',
      data: nodes,
      symbolKeepAspect: true,
      emphasis: { focus: 'self', scale: 1.3 },
      z: 3,
    }],
    dataZoom: [
      { type: 'inside', xAxisIndex: 0, filterMode: 'none' },
      { type: 'inside', yAxisIndex: 0, filterMode: 'none' },
    ],
  };
}

function emptyGraphOption(msg) {
  return {
    series: [{ type: 'graph', data: [], links: [], layout: 'none' }],
    graphic: {
      type: 'text', left: 'center', top: 'center',
      style: { text: msg, fill: '#9a938a', fontSize: 14 },
    },
  };
}

// ─── Detail panel ───
function selectPaper(paperId) {
  const d = currentDomain();
  const p = d.papers.find(x => x.paper_id === paperId);
  if (!p) return;
  state.selectedNode = { kind: 'paper', id: paperId };

  const cardText = d.cards[paperId];
  const entities = (d.paper_entities[paperId] || [])
    .map(eid => d.entities.find(e => e.entity_id === eid))
    .filter(Boolean);

  const body = document.getElementById('detailBody');
  body.innerHTML = `
    <div class="detail-section">
      <div class="detail-section__title">${p.evidence_tier === 'evidence_card' ? '证据卡论文' : '元数据记录'}</div>
      <h2 class="detail-title">${escapeHtml(p.title)}</h2>
      <div class="detail-meta">
        <div class="detail-meta__row"><span class="detail-meta__label">作者</span><span class="detail-meta__value">${escapeHtml(p.authors.slice(0, 6).join(', '))}${p.authors.length > 6 ? ' 等' : ''}</span></div>
        <div class="detail-meta__row"><span class="detail-meta__label">期刊</span><span class="detail-meta__value" style="color:var(--nature-red);font-weight:600">${escapeHtml(p.venue)}</span></div>
        <div class="detail-meta__row"><span class="detail-meta__label">年份</span><span class="detail-meta__value">${p.year}</span></div>
        <div class="detail-meta__row"><span class="detail-meta__label">DOI</span><span class="detail-meta__value"><a href="https://doi.org/${p.doi}" target="_blank" rel="noopener">${p.doi}</a></span></div>
        <div class="detail-meta__row"><span class="detail-meta__label">引用</span><span class="detail-meta__value">${p.citation_count}（OpenAlex 快照）</span></div>
      </div>
      <div class="detail-stats">
        <div class="detail-stat"><div class="detail-stat__num">${entities.length}</div><div class="detail-stat__label">涉及实体</div></div>
        <div class="detail-stat"><div class="detail-stat__num">${p.evidence_tier === 'evidence_card' ? '✓' : '—'}</div><div class="detail-stat__label">证据卡</div></div>
        <div class="detail-stat"><div class="detail-stat__num">${(p.concepts || []).length}</div><div class="detail-stat__label">概念</div></div>
      </div>
    </div>
    ${cardText ? `<div class="detail-section"><div class="detail-section__title">证据卡（基于公开摘要释义）</div><div class="evidence-card">${renderCard(cardText)}</div></div>` : ''}
    ${entities.length ? `<div class="detail-section"><div class="detail-section__title">涉及实体（点击查看）</div><div class="relation-list">${entities.map(e => `
      <div class="relation-item" data-entity="${e.entity_id}" style="cursor:pointer">
        <span class="legend-dot" style="background:${COLORS[e.entity_type]||'#999'}"></span>
        <span class="relation-source">${escapeHtml(e.canonical_name)}</span>
        <span style="color:var(--ink-faint)">· ${TYPE_LABELS[e.entity_type]||e.entity_type}</span>
      </div>`).join('')}</div></div>` : ''}
  `;
  body.querySelectorAll('[data-entity]').forEach(el => {
    el.addEventListener('click', () => selectEntity(el.dataset.entity));
  });
  renderPaperList();
  document.getElementById('statusSelection').textContent = `选中: ${p.title.slice(0, 30)}…`;
}

function selectEntity(entityId) {
  const d = currentDomain();
  const e = d.entities.find(x => x.entity_id === entityId);
  if (!e) return;
  state.selectedNode = { kind: 'entity', id: entityId };

  const rels = d.relations.filter(r => r.source_id === entityId || r.target_id === entityId);
  const paperIds = new Set();
  (d.paper_entities && Object.entries(d.paper_entities)).forEach(([pid, eids]) => {
    if (eids.includes(entityId)) paperIds.add(pid);
  });
  const papers = [...paperIds].map(pid => d.papers.find(p => p.paper_id === pid)).filter(Boolean)
    .sort((a,b) => b.citation_count - a.citation_count);

  const body = document.getElementById('detailBody');
  body.innerHTML = `
    <div class="detail-section">
      <div class="detail-section__title">实体</div>
      <h2 class="detail-title">
        <span class="legend-dot" style="display:inline-block;width:12px;height:12px;background:${COLORS[e.entity_type]||'#999'};margin-right:6px;vertical-align:middle"></span>
        ${escapeHtml(e.canonical_name)}
      </h2>
      <div class="detail-meta">
        <div class="detail-meta__row"><span class="detail-meta__label">类型</span><span class="detail-meta__value">${TYPE_LABELS[e.entity_type]||e.entity_type}</span></div>
        <div class="detail-meta__row"><span class="detail-meta__label">置信度</span><span class="detail-meta__value">${(e.confidence*100).toFixed(0)}%</span></div>
        <div class="detail-meta__row"><span class="detail-meta__label">提及</span><span class="detail-meta__value">${e.mention_count} 次 · ${papers.length} 篇论文</span></div>
        ${(e.aliases||[]).length ? `<div class="detail-meta__row"><span class="detail-meta__label">别名</span><span class="detail-meta__value">${e.aliases.slice(0,8).map(escapeHtml).join(', ')}</span></div>` : ''}
      </div>
      <div class="detail-stats">
        <div class="detail-stat"><div class="detail-stat__num">${rels.length}</div><div class="detail-stat__label">关系</div></div>
        <div class="detail-stat"><div class="detail-stat__num">${papers.length}</div><div class="detail-stat__label">论文</div></div>
        <div class="detail-stat"><div class="detail-stat__num" style="color:${rels.filter(r=>r.status==='accepted').length?'var(--c-dataset)':'var(--ink-faint)'}">${rels.filter(r=>r.status==='accepted').length}</div><div class="detail-stat__label">已接受</div></div>
      </div>
    </div>
    <div class="detail-section"><div class="detail-section__title">关系（${rels.length}）</div><div class="relation-list">
      ${rels.map(r => {
        const isSource = r.source_id === entityId;
        const other = isSource ? r.target_name : r.source_name;
        const otherId = isSource ? r.target_id : r.source_id;
        const arrow = isSource ? '→' : '←';
        return `<div class="relation-item" data-entity="${otherId}" style="cursor:pointer">
          <span class="relation-type" style="background:${REL_COLORS[r.relation_type]||'#999'}">${REL_LABELS[r.relation_type]||r.relation_type}</span>
          <span class="relation-arrow">${arrow}</span>
          <span class="relation-target">${escapeHtml(other)}</span>
          <span class="relation-conf">${(r.confidence*100).toFixed(0)}%</span>
        </div>`;
      }).join('')}
    </div></div>
    ${papers.length ? `<div class="detail-section"><div class="detail-section__title">支持论文（${papers.length}）</div><div class="relation-list">
      ${papers.slice(0,15).map(p => `<div class="relation-item" data-paper="${p.paper_id}" style="cursor:pointer">
        <span class="tier-badge tier-badge--${p.evidence_tier==='evidence_card'?'evidence':'metadata'}">${p.year}</span>
        <span class="relation-source" style="font-weight:400;font-size:11px">${escapeHtml(p.title.slice(0,60))}${p.title.length>60?'…':''}</span>
      </div>`).join('')}
      ${papers.length>15?`<div style="padding:6px 0;font-size:10px;color:var(--ink-faint)">…还有 ${papers.length-15} 篇</div>`:''}
    </div></div>` : ''}
  `;
  body.querySelectorAll('[data-entity]').forEach(el => {
    el.addEventListener('click', () => selectEntity(el.dataset.entity));
  });
  body.querySelectorAll('[data-paper]').forEach(el => {
    el.addEventListener('click', () => selectPaper(el.dataset.paper));
  });
  document.getElementById('statusSelection').textContent = `选中: ${e.canonical_name}`;
}

function renderCard(md) {
  // Minimal markdown-to-HTML for evidence cards
  return md
    .replace(/^# (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h3>$1</h3>')
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br/>')
    .replace(/^(.+)$/, '<p>$1</p>')
    .replace(/<p><h3>/g, '<h3>')
    .replace(/<\/h3><\/p>/g, '</h3>');
}

function countPapersForEntity(d, entityId) {
  let n = 0;
  Object.values(d.paper_entities || {}).forEach(eids => { if (eids.includes(entityId)) n++; });
  return n;
}

// ─── Meta bar ───
function renderMeta() {
  const d = currentDomain();
  document.getElementById('metaDomain').textContent = d.domain_name;
  document.getElementById('metaCounts').textContent =
    `${d.paper_count} 篇文献 · ${d.entity_count} 实体 · ${d.relation_count} 关系 · ${d.evidence_paper_count} 证据卡`;
}

// ─── Render all ───
function renderAll() {
  renderMeta();
  renderEntityLegend();
  renderPaperList();
  // Reset detail panel when switching domains
  if (!state.selectedNode) {
    document.getElementById('detailBody').innerHTML = `
      <div class="detail-empty">
        <div class="detail-empty__icon">◎</div>
        <p>点击图谱中的节点或左侧文献<br />查看论文元数据与证据卡</p>
      </div>`;
    document.getElementById('statusSelection').textContent = '未选中';
  }
  document.getElementById('graphLoading').classList.remove('is-hidden');
  setTimeout(() => {
    renderGraph();
    document.getElementById('graphLoading').classList.add('is-hidden');
  }, 50);
}

// ─── Event wiring ───
function wireEvents() {
  // View toggle
  document.getElementById('viewToggle').querySelectorAll('button').forEach(btn => {
    btn.addEventListener('click', () => {
      document.getElementById('viewToggle').querySelectorAll('button').forEach(b => b.classList.remove('is-active'));
      btn.classList.add('is-active');
      state.view = btn.dataset.view;
      renderGraph();
    });
  });

  // Search
  let searchTimer;
  document.getElementById('paperSearch').addEventListener('input', (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.search = e.target.value.trim();
      renderPaperList();
      if (state.view === 'timeline') renderGraph();
    }, 200);
  });

  // Year filters
  document.getElementById('yearMin').addEventListener('change', (e) => {
    state.yearMin = e.target.value ? parseInt(e.target.value) : null;
    renderPaperList();
    if (state.view === 'timeline') renderGraph();
  });
  document.getElementById('yearMax').addEventListener('change', (e) => {
    state.yearMax = e.target.value ? parseInt(e.target.value) : null;
    renderPaperList();
    if (state.view === 'timeline') renderGraph();
  });

  // Sort
  document.getElementById('sortBy').addEventListener('change', (e) => {
    state.sortBy = e.target.value;
    renderPaperList();
  });

  // Tier toggle
  document.getElementById('tierToggle').querySelectorAll('input').forEach(cb => {
    cb.addEventListener('change', () => {
      state.tiers = new Set(
        [...document.getElementById('tierToggle').querySelectorAll('input:checked')].map(c => c.value)
      );
      renderPaperList();
      if (state.view === 'timeline') renderGraph();
    });
  });

  // Panel collapse
  document.getElementById('collapseLeft').addEventListener('click', () => {
    document.getElementById('leftPanel').classList.toggle('is-collapsed');
    state.chart && state.chart.resize();
  });
  document.getElementById('collapseRight').addEventListener('click', () => {
    document.getElementById('rightPanel').classList.toggle('is-collapsed');
    state.chart && state.chart.resize();
  });

  // Resize
  window.addEventListener('resize', () => state.chart && state.chart.resize());
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// ─── Init ───
(async function init() {
  try {
    state.data = await loadData();
    state.domainId = state.data.domains[4]?.domain_id || state.data.domains[0].domain_id; // quantum-computing
    wireEvents();
    renderDomainTabs();
    renderAll();
  } catch (err) {
    document.getElementById('graphLoading').innerHTML =
      `<span style="color:#c0392b">数据加载失败: ${escapeHtml(err.message)}</span>`;
    console.error(err);
  }
})();
