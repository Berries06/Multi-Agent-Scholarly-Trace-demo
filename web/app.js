const appScriptPath = new URL(document.currentScript.src).pathname;
const APP_BASE = appScriptPath.endsWith("/app.js")
  ? appScriptPath.slice(0, -"/app.js".length)
  : "";

const state = {
  domains: [],
  selectedDomainId: "scientific-ie-kg",
  profiles: [],
  selectedProfileId: "undergraduate_ai",
  result: null,
  activeTab: "briefing",
  user: null,
  registrationOpen: false,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function idempotencyKey(prefix) {
  const suffix =
    globalThis.crypto?.randomUUID?.() ||
    `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${suffix}`;
}

function showRuntimeError(message = "") {
  const container = $("#runtime-error");
  container.textContent = message;
  container.hidden = !message;
}

async function requestJson(path, options = {}, timeoutMs = 15000) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const requestUrl = `${APP_BASE}${normalizedPath}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const headers = new Headers(options.headers || {});
  headers.set("X-Request-ID", `web-${idempotencyKey("request")}`.slice(0, 120));
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  try {
    const response = await fetch(requestUrl, {
      ...options,
      headers,
      signal: controller.signal,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const apiError = payload.error;
      const message =
        typeof apiError === "object"
          ? `${apiError.message || "请求失败"}（${apiError.code || response.status}）`
          : apiError || `请求失败（HTTP ${response.status}）`;
      throw new Error(message);
    }
    payload._transport = {
      requestId: response.headers.get("X-Request-ID"),
      runId: response.headers.get("X-Run-ID"),
      replayed: response.headers.get("Idempotency-Replayed") === "true",
    };
    return payload;
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error(`请求超过 ${Math.round(timeoutMs / 1000)} 秒，已安全中止`);
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

function setAccountMessage(message, isError = false) {
  const target = $("#account-message");
  target.textContent = message;
  target.className = "provider-test-status";
  target.classList.toggle("error", isError);
}

function showAuthMode(mode) {
  const registering = mode === "register";
  $("#login-form").hidden = registering;
  $("#register-form").hidden = !registering;
  $("#show-login-button").classList.toggle("active", !registering);
  $("#show-register-button").classList.toggle("active", registering);
  $("#show-login-button").setAttribute("aria-selected", String(!registering));
  $("#show-register-button").setAttribute("aria-selected", String(registering));
  setAccountMessage("");
  const focusTarget = registering ? $("#register-email") : $("#login-identifier");
  window.setTimeout(() => focusTarget?.focus(), 0);
}

function renderAccount() {
  const authenticated = Boolean(state.user);
  $("#auth-view").hidden = authenticated;
  $("#app-view").hidden = !authenticated;
  if (authenticated) {
    $("#account-status").textContent =
      `${state.user.profile?.name || state.user.nickname || "用户"} · ${state.user.email} · 画像 v${state.user.profile_version}`;
  } else {
    $("#show-register-button").disabled = !state.registrationOpen;
    $("#registration-status").textContent = state.registrationOpen
      ? "注册只需要邮箱、昵称和密码，详细学习画像可在登录后完善。"
      : "当前暂未开放新账号注册，已有用户仍可正常登录。";
  }
}

async function registerAccount() {
  const button = $("#register-button");
  button.disabled = true;
  try {
    const payload = await requestJson("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({
        email: $("#register-email").value.trim(),
        nickname: $("#register-nickname").value.trim(),
        password: $("#register-password").value,
      }),
    });
    state.user = payload.user;
    setAccountMessage("");
    renderAccount();
    initialize();
  } catch (error) {
    setAccountMessage(`注册失败：${error.message}`, true);
  } finally {
    button.disabled = false;
  }
}

async function loginAccount() {
  const button = $("#login-button");
  button.disabled = true;
  try {
    const payload = await requestJson("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        identifier: $("#login-identifier").value.trim(),
        password: $("#login-password").value,
      }),
    });
    state.user = payload.user;
    setAccountMessage("");
    renderAccount();
    initialize();
  } catch (error) {
    setAccountMessage(`登录失败：${error.message}`, true);
  } finally {
    button.disabled = false;
  }
}

async function logoutAccount() {
  try {
    await requestJson("/api/auth/logout", { method: "POST", body: "{}" });
    state.user = null;
    setAccountMessage("已退出登录。");
    renderAccount();
  } catch (error) {
    setAccountMessage(`退出失败：${error.message}`, true);
  }
}

function renderProfiles() {
  const container = $("#profile-list");
  container.innerHTML = state.profiles
    .map(
      (profile) => `
        <button
          class="profile-card ${profile.profile_id === state.selectedProfileId ? "active" : ""}"
          data-profile="${escapeHtml(profile.profile_id)}"
          type="button"
        >
          <strong>${escapeHtml(profile.name)} · ${escapeHtml(profile.education)}</strong>
          <span>${escapeHtml(profile.role)}</span>
          <small>${escapeHtml(profile.persona)}</small>
        </button>
      `,
    )
    .join("");
  $$(".profile-card").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedProfileId = button.dataset.profile;
      renderProfiles();
    });
  });
}

function renderDomains() {
  const select = $("#domain-select");
  select.innerHTML = state.domains
    .map(
      (domain) => `
        <option value="${escapeHtml(domain.domain_id)}" ${
          domain.domain_id === state.selectedDomainId ? "selected" : ""
        }>
          ${escapeHtml(domain.domain_name)}
        </option>
      `,
    )
    .join("");
  const selected = state.domains.find(
    (domain) => domain.domain_id === state.selectedDomainId,
  );
  if (!selected) return;
  $("#domain-description").textContent = selected.description;
  $("#domain-stats").innerHTML = `
    <span>${selected.paper_count} 篇收录 / ${selected.evidence_paper_count} 篇证据层</span>
    <span>${selected.metadata_only_paper_count} 篇待全文解析</span>
    <span>版本 ${escapeHtml(selected.version)}</span>
    <span>${selected.is_default ? "核心领域" : "扩展领域"}</span>
  `;
}

function percent(value) {
  return `${Number(value).toFixed(value % 1 ? 1 : 0)}%`;
}

function intervalPercent(interval) {
  return `${percent(interval[0] * 100)}–${percent(interval[1] * 100)}`;
}

function renderMetrics(result) {
  const triad = result.ablation.variants.find(
    (item) => item.variant_id === "evidence_triad",
  ).metrics;
  const quality = result.knowledge_graph.audit.quality;
  $("#metric-hallucination").textContent = percent(
    triad.accepted_precision * 100,
  );
  $("#metric-hallucination-note").textContent =
    `${triad.true_positive_count}/${triad.accepted_count} · 95% CI ${intervalPercent(triad.accepted_precision_ci95)}`;
  $("#metric-adaptation").textContent = percent(
    triad.unsupported_acceptance_rate * 100,
  );
  $("#metric-adaptation-note").textContent =
    `${triad.false_positive_count}/${triad.gold_unsupported_count} · 越低越好`;
  $("#metric-coverage").textContent = percent(
    triad.gold_recall * 100,
  );
  $("#metric-coverage-note").textContent =
    `${triad.true_positive_count}/${triad.gold_supported_count} · 95% CI ${intervalPercent(triad.gold_recall_ci95)}`;
  $("#metric-graph-scale").innerHTML =
    `<b>${quality.paper_count}</b> 论文 · <b>${quality.entity_count}</b> 实体<br /><b>${quality.relation_count}</b> 候选关系 · 证据绑定 ${percent(quality.relation_evidence_coverage * 100)}（结构约束）`;
}

function renderTrace(result) {
  const trace = result.agent_trace;
  const runId = result.observability?.run_id || result._transport?.runId;
  const runLabel = runId ? ` · ${runId.slice(0, 12)}` : "";
  $("#trace-summary").textContent =
    `${result.domain.domain_name} · ${result.core_method.system_agent_count} 个协同角色 / ${trace.length} 个决策 Agent${runLabel}`;
  $("#agent-trace").innerHTML = trace
    .map(
      (item, index) => `
        <article class="trace-step">
          <span class="trace-index">${String(index + 1).padStart(2, "0")}</span>
          <strong>${escapeHtml(item.agent)}</strong>
          <span>${escapeHtml(item.summary)}</span>
          <small>${item.duration_ms} ms</small>
        </article>
      `,
    )
    .join("");
}

function renderSpecialists(result) {
  $("#specialist-agent-trace").innerHTML = result.specialist_agent_trace
    .map((item) => {
      const details = item.details;
      const badge =
        item.role === "意图识别与检索路由"
          ? `${details.route} · ${percent(details.confidence * 100)}`
          : `${details.knowledge_concepts} 概念 · ${details.evidence_spans} 证据`;
      return `
        <article class="specialist-card">
          <div>
            <span>${escapeHtml(item.role)}</span>
            <strong>${escapeHtml(item.agent)}</strong>
          </div>
          <p>${escapeHtml(item.summary)}</p>
          <small>${escapeHtml(badge)}</small>
        </article>
      `;
    })
    .join("");
}

function truncate(text, length = 18) {
  return text.length > length ? `${text.slice(0, length)}…` : text;
}

function renderConceptGraph(payload) {
  const svg = $("#query-concept-graph");
  const nodes = payload.nodes.slice(0, 18);
  const visibleIds = new Set(nodes.map((node) => node.id));
  const groups = {
    method: nodes.filter((node) => node.entity_type === "METHOD"),
    task: nodes.filter((node) => node.entity_type === "TASK"),
    support: nodes.filter(
      (node) => !["METHOD", "TASK"].includes(node.entity_type),
    ),
  };
  const rowConfig = {
    method: { y: 75, start: 75, end: 825 },
    task: { y: 220, start: 75, end: 825 },
    support: { y: 360, start: 75, end: 825 },
  };
  const positions = new Map();
  Object.entries(groups).forEach(([kind, items]) => {
    const config = rowConfig[kind];
    items.forEach((node, index) => {
      const span =
        items.length > 1 ? (config.end - config.start) / (items.length - 1) : 0;
      positions.set(node.id, {
        x: items.length === 1 ? 450 : config.start + span * index,
        y: config.y,
      });
    });
  });
  const edges = payload.edges
    .filter(
      (edge) =>
        visibleIds.has(edge.source) &&
        visibleIds.has(edge.target) &&
        positions.has(edge.source) &&
        positions.has(edge.target),
    )
    .slice(0, 24)
    .map((edge) => {
      const source = positions.get(edge.source);
      const target = positions.get(edge.target);
      return `
        <g>
          <line class="concept-edge" x1="${source.x}" y1="${source.y}" x2="${target.x}" y2="${target.y}" />
          <text class="concept-edge-label" x="${(source.x + target.x) / 2}" y="${(source.y + target.y) / 2 - 5}">${escapeHtml(edge.label)}</text>
        </g>
      `;
    })
    .join("");
  const colors = {
    METHOD: "#087f78",
    TASK: "#3d6c8f",
    DATASET: "#d79232",
    METRIC: "#9a7048",
    FINDING: "#8b5d9b",
    LIMITATION: "#c96148",
    DOMAIN: "#60767b",
  };
  const renderedNodes = nodes
    .filter((node) => positions.has(node.id))
    .map((node) => {
      const position = positions.get(node.id);
      return `
        <g class="concept-node ${node.is_seed ? "seed" : ""}">
          ${node.is_seed ? `<circle class="seed-ring" cx="${position.x}" cy="${position.y}" r="22" />` : ""}
          <circle cx="${position.x}" cy="${position.y}" r="${node.is_seed ? 15 : 12}" fill="${colors[node.entity_type] || "#60767b"}" />
          <text x="${position.x}" y="${position.y + 31}">${escapeHtml(truncate(node.label, 17))}</text>
        </g>
      `;
    })
    .join("");
  svg.innerHTML = `${edges}${renderedNodes}`;
}

function renderGraphRetrieval(result) {
  const retrieval = result.graph_retrieval;
  const intent = retrieval.intent;
  const plan = retrieval.retrieval_plan;
  $("#intent-label").textContent =
    `${intent.label} · ${percent(intent.confidence * 100)}`;
  $("#retrieval-route").textContent =
    `${plan.route} ↔ ${retrieval.implementation.official_analogue}`;
  $("#retrieval-reason").textContent = plan.reason;
  $("#retrieval-scale").textContent =
    `${plan.visited_concepts} 概念 · ${plan.selected_relationships} 关系`;
  $("#retrieval-seeds").textContent =
    `种子：${retrieval.seed_entities.map((item) => item.label).join("、") || "高连接概念回退"}`;
  $("#graph-answer-summary").textContent = retrieval.answer.summary;
  renderConceptGraph(retrieval.concept_subgraph);
  $("#graph-paper-recommendations").innerHTML = retrieval.recommended_papers
    .slice(0, 5)
    .map(
      (paper, index) => `
        <a href="${escapeHtml(paper.source_url)}" target="_blank" rel="noreferrer">
          <span>${String(index + 1).padStart(2, "0")} · ${paper.year}</span>
          <strong>${escapeHtml(paper.title)}</strong>
          <small>${escapeHtml(paper.recommendation_reason)}</small>
        </a>
      `,
    )
    .join("");
  $("#graph-followups").innerHTML = retrieval.answer.follow_up_questions
    .map((question) => `<li>${escapeHtml(question)}</li>`)
    .join("");
}

function renderGraph(payload) {
  const svg = $("#knowledge-graph");
  const entityById = new Map(
    payload.entities.map((entity) => [entity.entity_id, entity]),
  );
  const evidenceById = new Map(
    payload.evidence.map((evidence) => [evidence.evidence_id, evidence]),
  );
  const acceptedRelations = payload.relations
    .filter((relation) => relation.status === "accepted")
    .slice(0, 12);
  const entityIds = new Set(
    acceptedRelations.flatMap((relation) => [
      relation.source_id,
      relation.target_id,
    ]),
  );
  const paperIds = [
    ...new Set(
      acceptedRelations.flatMap((relation) =>
        relation.evidence_ids
          .map((id) => evidenceById.get(id)?.paper_id)
          .filter(Boolean),
      ),
    ),
  ].slice(0, 8);
  const nodes = [
    ...paperIds.map((paperId) => {
      const paper = payload.papers.find((item) => item.paper_id === paperId);
      return {
        id: `paper:${paperId}`,
        label: paper?.title || paperId,
        kind: "paper",
      };
    }),
    ...[...entityIds].map((id) => {
      const entity = entityById.get(id);
      const type = entity?.entity_type || "FINDING";
      return {
        id,
        label: entity?.canonical_name || id,
        kind: ["METHOD", "DATASET"].includes(type) ? "concept" : "outcome",
      };
    }),
  ];
  const groups = {
    paper: nodes.filter((node) => node.kind === "paper"),
    concept: nodes.filter((node) => node.kind === "concept"),
    outcome: nodes.filter((node) => node.kind === "outcome"),
  };
  const positions = new Map();
  const rowConfig = {
    paper: { y: 70, start: 65, end: 835 },
    evidence_span: { y: 150, start: 65, end: 835 },
    concept: { y: 225, start: 90, end: 810 },
    outcome: { y: 365, start: 90, end: 810 },
  };
  Object.entries(groups).forEach(([kind, nodes]) => {
    const config = rowConfig[kind];
    nodes.forEach((node, index) => {
      const span = nodes.length > 1 ? (config.end - config.start) / (nodes.length - 1) : 0;
      positions.set(node.id, {
        x: nodes.length === 1 ? 450 : config.start + span * index,
        y: config.y,
      });
    });
  });

  const relationEdges = acceptedRelations.map((relation) => ({
    source: relation.source_id,
    target: relation.target_id,
    label: relation.relation_type,
  }));
  const evidenceEdges = acceptedRelations.flatMap((relation) =>
    relation.evidence_ids
      .map((id) => evidenceById.get(id)?.paper_id)
      .filter((paperId) => paperIds.includes(paperId))
      .map((paperId) => ({
        source: `paper:${paperId}`,
        target: relation.source_id,
        label: "evidence",
      })),
  );
  const uniqueEdges = [
    ...new Map(
      [...relationEdges, ...evidenceEdges].map((edge) => [
        `${edge.source}|${edge.target}|${edge.label}`,
        edge,
      ]),
    ).values(),
  ];
  const edges = uniqueEdges
    .filter((edge) => positions.has(edge.source) && positions.has(edge.target))
    .map((edge) => {
      const source = positions.get(edge.source);
      const target = positions.get(edge.target);
      return `
        <g>
          <line
            class="graph-edge ${edge.label === "evidence" ? "evidence" : ""}"
            x1="${source.x}" y1="${source.y}" x2="${target.x}" y2="${target.y}"
          />
          ${
            edge.label !== "evidence"
              ? `<text class="graph-label" x="${(source.x + target.x) / 2}" y="${(source.y + target.y) / 2 - 5}">${escapeHtml(edge.label)}</text>`
              : ""
          }
        </g>
      `;
    })
    .join("");

  const colors = { paper: "#3d6c8f", concept: "#087f78", outcome: "#d79232" };
  const renderedNodes = nodes
    .filter((node) => positions.has(node.id))
    .map((node) => {
      const position = positions.get(node.id);
      const radius = node.kind === "paper" || node.kind === "evidence_span" ? 9 : 15;
      return `
        <g class="graph-node">
          <circle cx="${position.x}" cy="${position.y}" r="${radius}" fill="${colors[node.kind]}" />
          <text x="${position.x}" y="${position.y + 31}">
            ${escapeHtml(truncate(node.label, ["paper", "evidence_span"].includes(node.kind) ? 15 : 18))}
          </text>
        </g>
      `;
    })
    .join("");
  svg.innerHTML = `${edges}${renderedNodes}`;
}

function renderReport(result) {
  $("#report-persona").textContent = result.profile.persona;
  $("#match-score").textContent = `${result.report.resource_match_score}%`;
  const scores = result.profile.knowledge_scores;
  $("#knowledge-bars").innerHTML = Object.entries(scores)
    .map(
      ([topic, score]) => `
        <div class="knowledge-bar">
          <span>${escapeHtml(topic)}</span>
          <div class="bar-track"><div class="bar-fill" style="width: ${score}%"></div></div>
          <b>${score}</b>
        </div>
      `,
    )
    .join("");
  $("#difficulty-curve").innerHTML = result.report.difficulty_curve
    .map(
      (point) => `
        <div class="difficulty-point" style="height: ${point.difficulty * 13}px">
          <span>${escapeHtml(point.stage)}</span>
        </div>
      `,
    )
    .join("");
  $("#learning-path").innerHTML = result.report.learning_path
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");
}

function renderClaims(result) {
  $("#claim-table").innerHTML = result.claims
    .map((claim) => {
      const evidence = claim.evidence_ids.length
        ? claim.evidence_ids
            .map((id) => `<span class="evidence-chip">${escapeHtml(id)}</span>`)
            .join("")
        : '<span class="evidence-chip">无来源</span>';
      const criticism = claim.criticisms
        .slice(0, 2)
        .map(escapeHtml)
        .join("<br />");
      const span = result.evidence_details[claim.claim_id]?.[0];
      const evidenceSnippet = span
        ? `<small class="evidence-snippet">${escapeHtml(span.paper_id)} · ${escapeHtml(span.section_id)}<br />“${escapeHtml(truncate(span.text, 74))}”</small>`
        : "";
      const label = {
        accepted: "通过",
        needs_review: "复核",
        rejected: "拒绝",
        abstained: "拒答",
      }[claim.status];
      return `
        <tr>
          <td>
            <span class="claim-main">${escapeHtml(claim.source)} ${escapeHtml(claim.relation)} ${escapeHtml(claim.target)}</span>
          </td>
          <td>${evidence}${evidenceSnippet}</td>
          <td>${criticism}</td>
          <td>
            <span class="verdict ${claim.status}">${label} · ${percent(claim.judge_score * 100)}</span>
            <small class="judge-reason">${escapeHtml(claim.judge_reason)}</small>
          </td>
        </tr>
      `;
    })
    .join("");
}

function renderAblation(result) {
  const ablation = result.ablation;
  const triadVariant = ablation.variants.find(
    (item) => item.variant_id === "evidence_triad",
  );
  const triadErrors = triadVariant.cases.filter((item) => !item.correct).length;
  $("#ablation-gain").textContent =
    `24 条压力集 · 本方法仍错 ${triadErrors} 条 · 较最佳基线 +${ablation.comparison.accepted_precision_gain_pp.toFixed(1)} pp`;
  $("#ablation-table").innerHTML = ablation.variants
    .map((variant) => {
      const metrics = variant.metrics;
      const featured = variant.variant_id === "evidence_triad";
      return `
        <tr class="${featured ? "featured-row" : ""}">
          <td><strong>${escapeHtml(variant.label)}</strong>${featured ? '<span class="method-tag">本项目</span>' : ""}</td>
          <td>${percent(metrics.accepted_precision * 100)}<small>${metrics.true_positive_count}/${metrics.accepted_count}</small></td>
          <td>${percent(metrics.gold_recall * 100)}<small>${metrics.true_positive_count}/${metrics.gold_supported_count}</small></td>
          <td>${percent(metrics.unsupported_acceptance_rate * 100)}<small>${metrics.false_positive_count}/${metrics.gold_unsupported_count}</small></td>
          <td>${percent(metrics.evidence_coverage * 100)}<small>结构约束</small></td>
        </tr>
      `;
    })
    .join("");
  $("#ablation-warning").textContent = ablation.warning;
}

function renderInsights(result) {
  const timeline = result.graph_insights.timeline.filter(
    (item) => item.contributions.length,
  );
  $("#literature-timeline").innerHTML = timeline
    .map(
      (item) => `
        <li>
          <time>${item.year}</time>
          <div>
            <a href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(item.title)}</a>
            <p>${item.contributions.map(escapeHtml).join("<br />")}</p>
          </div>
        </li>
      `,
    )
    .join("");
  const ideas = result.graph_insights.research_ideas;
  $("#research-ideas").innerHTML = ideas.length
    ? ideas
        .map(
          (idea) => `
            <article class="idea-card">
              <span class="unverified-tag">新颖性未验证</span>
              <h3>${escapeHtml(idea.title)}</h3>
              <p>${escapeHtml(idea.hypothesis)}</p>
              <details>
                <summary>查看图谱推理依据</summary>
                <ul>${idea.graph_basis.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
              </details>
            </article>
          `,
        )
        .join("")
    : '<p class="scope-warning">当前子图没有满足约束的缺失边候选。</p>';
}

async function runOnlineRag() {
  const button = $("#online-rag-button");
  button.disabled = true;
  button.textContent = "正在检索 OpenAlex…";
  try {
    const payload = await requestJson("/api/online-rag", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey("online-rag") },
      body: JSON.stringify({
        domain_id: state.selectedDomainId,
        query: $("#research-query").value.trim(),
        limit: 5,
        allow_network: true,
      }),
    }, 20000);
    $("#online-rag-status").textContent = payload.warning;
    $("#online-rag-results").innerHTML = payload.results.length
      ? payload.results
          .map(
            (paper) => `
              <a class="rag-result" href="${escapeHtml(paper.source_url)}" target="_blank" rel="noreferrer">
                <span>${paper.year || "—"} · ${escapeHtml(paper.venue || "来源待核验")}</span>
                <strong>${escapeHtml(paper.title)}</strong>
                <small>${escapeHtml(paper.status)}</small>
              </a>
            `,
          )
          .join("")
      : '<p class="scope-warning">未返回候选；本地垂直知识库仍可离线运行。</p>';
  } catch (error) {
    $("#online-rag-status").textContent =
      `联网检索失败：${error.message}。本地垂直知识库不受影响。`;
  } finally {
    button.disabled = false;
    button.textContent = "重新联网扩展";
  }
}

function renderBriefing(resources) {
  const briefing = resources.briefing;
  return `
    <h3 class="resource-title">${escapeHtml(briefing.title)}</h3>
    <p class="resource-strategy">L${briefing.level} 策略：${escapeHtml(briefing.strategy)}</p>
    ${briefing.sections
      .map(
        (section) => `
          <article class="brief-section">
            <h3>${escapeHtml(section.heading)}</h3>
            <p>${escapeHtml(section.body)}</p>
            <div>${section.citations.map((id) => `<span class="evidence-chip">${escapeHtml(id)}</span>`).join("")}</div>
          </article>
        `,
      )
      .join("")}
  `;
}

function renderGuide(resources) {
  const guide = resources.practical_guide;
  return `
    <h3 class="resource-title">${escapeHtml(guide.title)}</h3>
    <p class="resource-strategy">预计 ${guide.estimated_minutes} 分钟完成</p>
    ${guide.steps
      .map(
        (step) => `
          <article class="guide-step">
            <span class="step-number">${step.step}</span>
            <div>
              <h3>${escapeHtml(step.title)}</h3>
              <p>${escapeHtml(step.action)}</p>
            </div>
          </article>
        `,
      )
      .join("")}
  `;
}

function renderQuiz(resources) {
  const quiz = resources.quiz;
  return `
    <h3 class="resource-title">${escapeHtml(quiz.title)}</h3>
    <p class="resource-strategy">答案保存在结构化输出中，演示时可由评委现场作答。</p>
    ${quiz.items
      .map(
        (item, index) => `
          <article class="quiz-item">
            <h3>${index + 1}. [${escapeHtml(item.level)}] ${escapeHtml(item.question)}</h3>
            <div class="quiz-options">
              ${item.options
                .map(
                  (option, optionIndex) =>
                    `<span>${String.fromCharCode(65 + optionIndex)}. ${escapeHtml(option)}</span>`,
                )
                .join("")}
            </div>
          </article>
        `,
      )
      .join("")}
  `;
}

function renderResource() {
  if (!state.result) return;
  const resources = state.result.resources;
  const renderers = {
    briefing: renderBriefing,
    guide: renderGuide,
    quiz: renderQuiz,
  };
  $("#resource-content").innerHTML = renderers[state.activeTab](resources);
  $$(".tab-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === state.activeTab);
  });
  $("#blue-ocean-hypothesis").textContent = resources.blue_ocean.hypothesis;
  $("#blue-ocean-caveat").textContent = resources.blue_ocean.caveat;
}

function renderResult(result) {
  state.result = result;
  $("#empty-state").hidden = true;
  $("#result-content").hidden = false;
  renderMetrics(result);
  renderSpecialists(result);
  renderTrace(result);
  renderGraphRetrieval(result);
  renderGraph(result.knowledge_graph);
  renderReport(result);
  renderClaims(result);
  renderAblation(result);
  renderInsights(result);
  renderResource();
  $("#feedback-decision").textContent =
    result.feedback?.decision || "反馈会触发下一轮难度与解释策略更新。";
}

async function runFlow() {
  if (!state.user) {
    showRuntimeError("请先注册或登录后使用。");
    return;
  }
  const button = $("#run-button");
  const original = button.innerHTML;
  button.disabled = true;
  button.innerHTML = "<span>智能体协同中…</span><span>•••</span>";
  showRuntimeError();
  try {
    const result = await requestJson("/api/run", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey("run") },
      body: JSON.stringify({
        domain_id: state.selectedDomainId,
        profile_id: state.selectedProfileId,
        query: $("#research-query").value.trim(),
      }),
    });
    renderResult(result);
    $("#result-content").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showRuntimeError(`运行失败：${error.message}`);
  } finally {
    button.disabled = false;
    button.innerHTML = original;
  }
}

async function sendFeedback(feedback) {
  if (!state.result) return;
  const buttons = $$(".feedback-actions button");
  buttons.forEach((button) => {
    button.disabled = true;
  });
  showRuntimeError();
  try {
    const result = await requestJson("/api/feedback", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey("feedback") },
      body: JSON.stringify({
        domain_id: state.selectedDomainId,
        profile_id: state.selectedProfileId,
        query: $("#research-query").value.trim(),
        feedback,
      }),
    });
    renderResult(result);
  } catch (error) {
    showRuntimeError(`反馈更新失败：${error.message}`);
  } finally {
    buttons.forEach((button) => {
      button.disabled = false;
    });
  }
}

let _initialized = false;

async function initialize() {
  if (_initialized) {
    // 登录/注册后仅刷新数据与视图，不重复绑定事件
    try {
      const [profiles, authPayload] = await Promise.all([
        requestJson("/api/profiles", {}, 5000),
        requestJson("/api/auth/me", {}, 5000),
      ]);
      state.profiles = profiles.profiles;
      state.user = authPayload.user;
      renderProfiles();
      renderAccount();
    } catch (error) {
      /* 保持当前状态 */
    }
    return;
  }
  _initialized = true;
  try {
    const [health, profiles, domains, authPayload, authStatusPayload] =
      await Promise.all([
        requestJson("/api/health", {}, 5000),
        requestJson("/api/profiles", {}, 5000),
        requestJson("/api/domains", {}, 5000),
        requestJson("/api/auth/me", {}, 5000),
        requestJson("/api/auth/status", {}, 5000),
      ]);
    $("#backend-status").textContent =
      `后端在线 · ${health.domains} 个领域 / ${health.papers} 篇论文 · ${health.system_agents} 协同角色`;
    $("#hero-domain-count").textContent = health.domains;
    $("#hero-paper-count").textContent = health.papers;
    state.domains = domains.domains;
    state.selectedDomainId = domains.default_domain_id;
    renderDomains();
    state.profiles = profiles.profiles;
    state.user = authPayload.user;
    state.registrationOpen = Boolean(authStatusPayload.registration_open);
    renderProfiles();
    renderAccount();
  } catch (error) {
    $(".status-dot").classList.add("error");
    $("#backend-status").textContent = "后端不可用";
    showRuntimeError(`初始化失败：${error.message}`);
    $("#profile-list").innerHTML =
      `<p class="privacy-note">画像加载失败：${escapeHtml(error.message)}</p>`;
  }

  $("#domain-select").addEventListener("change", (event) => {
    state.selectedDomainId = event.target.value;
    const selected = state.domains.find(
      (domain) => domain.domain_id === state.selectedDomainId,
    );
    if (selected?.query_example) {
      $("#research-query").value = selected.query_example;
    }
    state.result = null;
    $("#result-content").hidden = true;
    $("#empty-state").hidden = false;
    renderDomains();
  });
  $("#run-button").addEventListener("click", runFlow);
  $("#online-rag-button").addEventListener("click", runOnlineRag);
  $("#login-form").addEventListener("submit", (event) => {
    event.preventDefault();
    loginAccount();
  });
  $("#register-form").addEventListener("submit", (event) => {
    event.preventDefault();
    registerAccount();
  });
  $("#show-login-button").addEventListener("click", () => showAuthMode("login"));
  $("#show-register-button").addEventListener("click", () => {
    if (state.registrationOpen) showAuthMode("register");
  });
  $("#logout-button").addEventListener("click", logoutAccount);
  $$(".tab-button").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeTab = button.dataset.tab;
      renderResource();
    });
  });
  $$(".feedback-actions button").forEach((button) => {
    button.addEventListener("click", () => sendFeedback(button.dataset.feedback));
  });
}

initialize();
