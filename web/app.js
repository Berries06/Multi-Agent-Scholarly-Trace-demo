const state = {
  profiles: [],
  selectedProfileId: "undergraduate_ai",
  result: null,
  activeTab: "briefing",
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

async function requestJson(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "请求失败");
  }
  return payload;
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

function percent(value) {
  return `${Number(value).toFixed(value % 1 ? 1 : 0)}%`;
}

function renderMetrics(result) {
  $("#metric-hallucination").textContent = percent(
    result.metrics.hallucination_proxy_rate,
  );
  $("#metric-adaptation").textContent = percent(
    result.metrics.adaptation_accuracy,
  );
  $("#metric-coverage").textContent = percent(
    result.metrics.knowledge_coverage_rate,
  );
}

function renderTrace(result) {
  const trace = result.agent_trace;
  $("#trace-summary").textContent =
    `${trace.length} 个固定 Agent · ${trace.reduce((sum, item) => sum + item.duration_ms, 0)} ms`;
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

function truncate(text, length = 18) {
  return text.length > length ? `${text.slice(0, length)}…` : text;
}

function renderGraph(graph) {
  const svg = $("#knowledge-graph");
  const groups = {
    paper: graph.nodes.filter((node) => node.kind === "paper"),
    concept: graph.nodes.filter((node) => node.kind === "concept"),
    outcome: graph.nodes.filter((node) => node.kind === "outcome"),
  };
  const positions = new Map();
  const rowConfig = {
    paper: { y: 70, start: 65, end: 835 },
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

  const edges = graph.edges
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
  const nodes = graph.nodes
    .filter((node) => positions.has(node.id))
    .map((node) => {
      const position = positions.get(node.id);
      const radius = node.kind === "paper" ? 11 : 15;
      return `
        <g class="graph-node">
          <circle cx="${position.x}" cy="${position.y}" r="${radius}" fill="${colors[node.kind]}" />
          <text x="${position.x}" y="${position.y + 31}">
            ${escapeHtml(truncate(node.label, node.kind === "paper" ? 15 : 18))}
          </text>
        </g>
      `;
    })
    .join("");
  svg.innerHTML = `${edges}${nodes}`;
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
      const label = {
        accepted: "通过",
        review: "复核",
        rejected: "拒绝",
      }[claim.status];
      return `
        <tr>
          <td>
            <span class="claim-main">${escapeHtml(claim.source)} ${escapeHtml(claim.relation)} ${escapeHtml(claim.target)}</span>
          </td>
          <td>${evidence}</td>
          <td>${criticism}</td>
          <td>
            <span class="verdict ${claim.status}">${label} · ${percent(claim.judge_score * 100)}</span>
          </td>
        </tr>
      `;
    })
    .join("");
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
  renderTrace(result);
  renderGraph(result.graph);
  renderReport(result);
  renderClaims(result);
  renderResource();
  $("#feedback-decision").textContent =
    result.feedback?.decision || "反馈会触发下一轮难度与解释策略更新。";
}

async function runFlow() {
  const button = $("#run-button");
  const original = button.innerHTML;
  button.disabled = true;
  button.innerHTML = "<span>智能体协同中…</span><span>•••</span>";
  try {
    const result = await requestJson("/api/run", {
      method: "POST",
      body: JSON.stringify({
        profile_id: state.selectedProfileId,
        query: $("#research-query").value.trim(),
      }),
    });
    renderResult(result);
    $("#result-content").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    window.alert(`运行失败：${error.message}`);
  } finally {
    button.disabled = false;
    button.innerHTML = original;
  }
}

async function sendFeedback(feedback) {
  if (!state.result) return;
  try {
    const result = await requestJson("/api/feedback", {
      method: "POST",
      body: JSON.stringify({
        profile_id: state.selectedProfileId,
        query: $("#research-query").value.trim(),
        feedback,
      }),
    });
    renderResult(result);
  } catch (error) {
    window.alert(`反馈更新失败：${error.message}`);
  }
}

async function initialize() {
  try {
    const payload = await requestJson("/api/profiles");
    state.profiles = payload.profiles;
    renderProfiles();
  } catch (error) {
    $("#profile-list").innerHTML =
      `<p class="privacy-note">画像加载失败：${escapeHtml(error.message)}</p>`;
  }

  $("#run-button").addEventListener("click", runFlow);
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
