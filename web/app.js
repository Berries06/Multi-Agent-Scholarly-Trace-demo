const appScriptPath = new URL(document.currentScript.src).pathname;
const APP_BASE = appScriptPath.endsWith("/app.js")
  ? appScriptPath.slice(0, -"/app.js".length)
  : "";

const state = {
  profiles: [],
  selectedProfileId: "undergraduate_ai",
  result: null,
  activeTab: "briefing",
  presets: [],
  selectedPreset: "full",
  providers: [],
  selectedProvider: "mock",
  user: null,
  experimentSessionId: null,
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
  const normalizedPath = `/${String(path).replace(/^\/+/, "")}`;
  const response = await fetch(`${APP_BASE}${normalizedPath}`, {
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
  const visibleProfiles = state.user ? [state.user.profile] : state.profiles;
  if (state.user) {
    state.selectedProfileId = state.user.profile.profile_id;
  }
  container.innerHTML = visibleProfiles
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

function renderAccount() {
  const authenticated = Boolean(state.user);
  $("#auth-forms").hidden = authenticated;
  $("#logout-button").hidden = !authenticated;
  $("#experiment-button").disabled =
    !authenticated || state.selectedProvider !== "mock";
  if (authenticated) {
    $("#account-status").textContent =
      `${state.user.profile.name} · ${state.user.email} · 画像 v${state.user.profile_version}`;
    $("#profile-mode-note").textContent =
      "当前询问自动使用你的长期画像；后续修改会形成新版本，不覆盖历史实验。";
    $("#auth-gate").hidden = true;
    $("#workbench-gated").hidden = false;
    $("#api-key-note").textContent =
      "已登录用户可直接选择「免费 DeepSeek (Flash)」，无需自备 Key。也可选择其他供应商并自填 Key。";
  } else {
    $("#account-status").textContent = "请注册或登录后使用研海寻踪。";
    $("#profile-mode-note").textContent = "";
    $("#auth-gate").hidden = false;
    $("#workbench-gated").hidden = true;
    $("#empty-state").hidden = true;
    $("#result-content").hidden = true;
    $("#api-key-note").textContent =
      "密钥仅经当前请求转发给所选供应商，不保存到本站、浏览器存储或日志。";
  }
  renderProfiles();
}

function splitProfileTerms(value) {
  return String(value)
    .split(/[,，;；]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function registrationProfilePayload() {
  const interests = splitProfileTerms($("#profile-interests").value);
  return {
    name: $("#profile-name").value.trim(),
    persona: "通过网站注册并持续完善的真实学习者画像",
    education: $("#profile-education").value.trim(),
    role: $("#profile-role").value.trim(),
    goal: $("#profile-goal").value.trim(),
    interests,
    knowledge_scores: {
      领域基础: 40,
      证据检索: 35,
      研究方法: 35,
    },
    preferred_style: $("#profile-style").value.trim(),
    expected_difficulty: Number($("#profile-difficulty").value),
    required_concepts: interests.length ? interests : ["证据判断"],
  };
}

function setAccountMessage(message, isError = false) {
  const target = $("#account-message");
  target.textContent = message;
  target.className = "provider-test-status";
  target.classList.add(isError ? "error" : "success");
}

async function registerAccount() {
  const button = $("#register-button");
  button.disabled = true;
  try {
    const payload = await requestJson("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({
        email: $("#auth-email").value.trim(),
        password: $("#auth-password").value,
        profile: registrationProfilePayload(),
      }),
    });
    state.user = payload.user;
    setAccountMessage("注册成功，个性化画像已建立。");
    renderAccount();
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
        email: $("#auth-email").value.trim(),
        password: $("#auth-password").value,
      }),
    });
    state.user = payload.user;
    setAccountMessage("登录成功，已切换到你的长期画像。");
    renderAccount();
  } catch (error) {
    setAccountMessage(`登录失败：${error.message}`, true);
  } finally {
    button.disabled = false;
  }
}

async function logoutAccount() {
  try {
    await requestJson("/api/auth/logout", {
      method: "POST",
      body: "{}",
    });
    state.user = null;
    state.experimentSessionId = null;
    $("#study-survey").hidden = true;
    setAccountMessage("已退出登录。");
    renderAccount();
  } catch (error) {
    setAccountMessage(`退出失败：${error.message}`, true);
  }
}

function percent(value) {
  return `${Number(value).toFixed(value % 1 ? 1 : 0)}%`;
}

function renderPresets() {
  const select = $("#preset-select");
  select.innerHTML = state.presets
    .map(
      (preset) =>
        `<option value="${escapeHtml(preset.name)}">${escapeHtml(preset.label)}</option>`,
    )
    .join("");
  select.value = state.selectedPreset;
  const updateDescription = () => {
    state.selectedPreset = select.value;
    const preset = state.presets.find((item) => item.name === select.value);
    $("#preset-description").textContent = preset?.description || "";
  };
  select.addEventListener("change", updateDescription);
  updateDescription();
}

function selectedProviderMetadata() {
  return state.providers.find((item) => item.id === state.selectedProvider);
}

function renderProviders() {
  const select = $("#provider-select");
  select.innerHTML = state.providers
    .map(
      (provider) =>
        `<option value="${escapeHtml(provider.id)}">${escapeHtml(provider.label)}</option>`,
    )
    .join("");
  select.value = state.selectedProvider;

  const updateProvider = (resetModel = false) => {
    state.selectedProvider = select.value;
    const provider = selectedProviderMetadata();
    $("#provider-description").textContent = provider?.description || "";
    $("#model-options").innerHTML = (provider?.models || [])
      .map((model) => `<option value="${escapeHtml(model)}"></option>`)
      .join("");
    if (resetModel || !$("#model-input").value) {
      $("#model-input").value = provider?.default_model || "";
    }
    const isMock = provider?.id === "mock";
    const isFreeDS = provider?.id === "free-deepseek";
    $("#api-key-field").hidden = isMock || isFreeDS;
    $("#model-input").hidden = isFreeDS;
    $("#model-input").disabled = isMock;
    const modelLabel = document.querySelector('label[for="model-input"]');
    if (modelLabel) modelLabel.hidden = isFreeDS;
    if (!isMock && !isFreeDS && resetModel) {
      $("#api-key-input").value = "";
    }
    const status = $("#provider-test-status");
    status.textContent = isMock
      ? "离线模式无需密钥；原有 mock 能力保持不变。"
      : "实时运行约 3 次模型调用；提交反馈会重新运行并产生新的用量。";
    status.className = "provider-test-status";
    $("#experiment-button").disabled = !state.user || !isMock;
  };

  select.addEventListener("change", () => updateProvider(true));
  updateProvider(true);
}

function llmPayload() {
  return {
    provider: state.selectedProvider,
    model: $("#model-input").value.trim(),
    api_key: state.selectedProvider === "mock" ? "" : $("#api-key-input").value.trim(),
  };
}

async function testProvider() {
  const button = $("#test-provider-button");
  const status = $("#provider-test-status");
  button.disabled = true;
  status.className = "provider-test-status";
  status.textContent = "正在验证连接…";
  try {
    const payload = await requestJson("/api/provider/test", {
      method: "POST",
      body: JSON.stringify({ llm: llmPayload() }),
    });
    status.textContent = payload.message;
    status.classList.add("success");
  } catch (error) {
    status.textContent = `连接失败：${error.message}`;
    status.classList.add("error");
  } finally {
    button.disabled = false;
  }
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

function renderInnovations(result) {
  const innovations = result.innovations || {};
  const falsification = innovations.falsification || {};
  const completed = Math.max(
    0,
    Number(falsification.rounds || 0) -
      Number(falsification.failed || 0) -
      Number(falsification.unresolved || 0),
  );
  $("#active-preset").textContent = result.system_config?.label || "基础链路";
  $("#falsification-summary").textContent = falsification.rounds
    ? `${completed} / ${falsification.failed} / ${falsification.unresolved}`
    : "未启用";
  $("#debate-summary").textContent = innovations.debate_view_count
    ? `${innovations.debate_view_count} 次`
    : "未启用";
  $("#gap-summary").textContent = innovations.discovery?.research_gaps
    ? `${innovations.discovery.research_gaps.length} 个`
    : "未启用";
  $("#probe-summary").textContent =
    result.provider_run?.mode === "live_llm"
      ? `${Number(result.provider_run.llm_duration_ms).toFixed(0)} ms`
      : result.performance?.total_ms == null
      ? "已关闭"
      : `${Number(result.performance.total_ms).toFixed(2)} ms`;

  const hypotheses = innovations.hypotheses || [];
  $("#hypothesis-ranking").innerHTML = hypotheses.length
    ? hypotheses
        .map(
          (item) => {
            const score =
              item.score == null ? "待验证" : `${Math.round(item.score * 100)}分`;
            return `<li><b>#${item.rank} · ${score}</b>${escapeHtml(item.hypothesis)}</li>`;
          },
        )
        .join("")
    : "<li>当前方案未启用假设锦标赛。</li>";

  const stages = [...(result.performance?.stages || [])]
    .sort((a, b) => b.duration_ms - a.duration_ms)
    .slice(0, 4);
  $("#probe-ranking").innerHTML = stages.length
    ? stages
        .map(
          (stage) =>
            `<li><b>${escapeHtml(stage.name)}</b>${Number(stage.duration_ms).toFixed(3)} ms</li>`,
        )
        .join("")
    : "<li>当前没有探针数据。</li>";
}

function renderProviderRun(result) {
  const run = result.provider_run || {};
  $("#provider-run-title").textContent =
    `${run.provider_label || "离线 Mock"} · ${run.model || "offline-rules"}`;
  const sourceLabels = {
    local_mock: "本地 mock",
    local_fallback: "本地降级",
    arxiv_live: "arXiv 实时来源",
    multi_source_live: "开放论文 + 官方文档",
    multi_source_live_with_local_cache: "开放来源 + 本地论文库",
    local_sqlite: "本地垂直领域论文库",
    no_relevant_sources: "未找到相关来源",
  };
  $("#provider-source-badge").textContent =
    sourceLabels[run.source_mode] || run.source_mode || "本地";
  const usage = run.usage || {};
  $("#provider-run-meta").innerHTML = [
    `模式 ${run.mode || "offline_mock"}`,
    `输入 ${Number(usage.input_tokens || 0)} tokens`,
    `输出 ${Number(usage.output_tokens || 0)} tokens`,
    `模型 ${Number(run.llm_duration_ms || 0).toFixed(0)} ms`,
    `检索 ${Number(run.retrieval_duration_ms || 0).toFixed(0)} ms`,
    (run.successful_sources || []).length
      ? `来源 ${(run.successful_sources || []).join(", ")}`
      : "",
    run.api_key_persisted === false ? "API Key 未持久化" : "",
  ]
    .filter(Boolean)
    .map((item) => `<span>${escapeHtml(item)}</span>`)
    .join("");

  const warnings = run.warnings || [];
  const warningBox = $("#provider-warnings");
  warningBox.hidden = warnings.length === 0;
  warningBox.textContent = warnings.join("；");

  const answerCard = $("#live-answer-card");
  const answer = result.answer || "";
  answerCard.hidden = !answer;
  $("#live-answer").textContent = answer;
}

function renderTrace(result) {
  const trace = result.agent_trace;
  $("#trace-summary").textContent =
    `${trace.length} 个执行轨迹步骤 · ${trace.reduce((sum, item) => sum + item.duration_ms, 0)} ms`;
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
    evidence_span: graph.nodes.filter((node) => node.kind === "evidence_span"),
    concept: graph.nodes.filter((node) => node.kind === "concept"),
    outcome: graph.nodes.filter((node) => node.kind === "outcome"),
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

  const colors = {
    paper: "#3d6c8f",
    evidence_span: "#7f8f67",
    concept: "#087f78",
    outcome: "#d79232",
  };
  const nodes = graph.nodes
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
        abstained: "拒答",
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
  renderProviderRun(result);
  renderInnovations(result);
  renderTrace(result);
  renderGraph(result.graph);
  renderReport(result);
  renderClaims(result);
  renderResource();
  $("#feedback-decision").textContent =
    result.feedback?.decision || "反馈会触发下一轮难度与解释策略更新。";
  const experiment = result.experiment;
  if (experiment) {
    state.experimentSessionId = experiment.research_session_id;
    $("#study-survey").hidden = false;
    $("#experiment-label").textContent =
      `请评价本轮随机展示的回答（${experiment.displayed_label}）`;
    $("#survey-status").textContent = "";
  } else {
    state.experimentSessionId = null;
    $("#study-survey").hidden = true;
  }
}

async function runFlow() {
  if (!state.user) {
    window.alert("请先注册或登录后使用。");
    return;
  }
  const button = $("#run-button");
  const original = button.innerHTML;
  button.disabled = true;
  button.innerHTML = "<span>智能体协同中…</span><span>•••</span>";
  try {
    const result = await requestJson("/api/run", {
      method: "POST",
      body: JSON.stringify({
        query: $("#research-query").value.trim(),
        preset: state.selectedPreset,
        llm: llmPayload(),
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

async function runExperiment() {
  if (!state.user) {
    window.alert("请先注册或登录，并建立自己的学习画像。");
    return;
  }
  if (state.selectedProvider !== "mock") {
    window.alert("本地消融采集 MVP 暂只支持离线 Mock。");
    return;
  }
  const button = $("#experiment-button");
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "正在生成并保存四个版本…";
  try {
    const result = await requestJson("/api/experiments/run", {
      method: "POST",
      body: JSON.stringify({
        query: $("#research-query").value.trim(),
        llm: llmPayload(),
      }),
    });
    renderResult(result);
    $("#result-content").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    window.alert(`对照实验失败：${error.message}`);
  } finally {
    button.disabled = !state.user || state.selectedProvider !== "mock";
    button.textContent = original;
  }
}

function initializeSurveyInputs() {
  const options = [1, 2, 3, 4, 5]
    .map(
      (score) =>
        `<option value="${score}" ${score === 4 ? "selected" : ""}>${score} 分</option>`,
    )
    .join("");
  $$("[data-survey]").forEach((select) => {
    select.innerHTML = options;
  });
}

async function submitSurvey() {
  if (!state.experimentSessionId) return;
  const button = $("#submit-survey-button");
  button.disabled = true;
  const answers = {};
  $$("[data-survey]").forEach((select) => {
    answers[select.dataset.survey] = Number(select.value);
  });
  answers.comment = $("#survey-comment").value.trim();
  try {
    await requestJson("/api/surveys", {
      method: "POST",
      body: JSON.stringify({
        research_session_id: state.experimentSessionId,
        answers,
      }),
    });
    $("#survey-status").textContent = "问卷已保存，感谢参与本轮对照实验。";
    $("#survey-status").className = "provider-test-status success";
  } catch (error) {
    $("#survey-status").textContent = `提交失败：${error.message}`;
    $("#survey-status").className = "provider-test-status error";
    button.disabled = false;
  }
}

async function sendFeedback(feedback) {
  if (!state.result) return;
  try {
    const result = await requestJson("/api/feedback", {
      method: "POST",
      body: JSON.stringify({
        query: $("#research-query").value.trim(),
        feedback,
        preset: state.selectedPreset,
        llm: llmPayload(),
      }),
    });
    renderResult(result);
  } catch (error) {
    window.alert(`反馈更新失败：${error.message}`);
  }
}

async function initialize() {
  try {
    const [
      profilePayload,
      configPayload,
      providerPayload,
      authPayload,
      libraryPayload,
    ] = await Promise.all([
      requestJson("/api/profiles"),
      requestJson("/api/configs"),
      requestJson("/api/providers"),
      requestJson("/api/auth/me"),
      requestJson("/api/library/slices"),
    ]);
    state.profiles = profilePayload.profiles;
    state.presets = configPayload.presets;
    state.selectedPreset = configPayload.default_demo_preset;
    state.providers = providerPayload.providers;
    state.selectedProvider = providerPayload.default_provider;
    state.user = authPayload.user;
    const nonEmptySlices = libraryPayload.slices.filter(
      (item) => Number(item.paper_count) > 0,
    );
    const totalPapers = nonEmptySlices.reduce(
      (sum, item) => sum + Number(item.paper_count),
      0,
    );
    $("#library-status").textContent =
      `本地论文库：${nonEmptySlices.length} 个有效垂直切片，${totalPapers} 条切片关联。`;
    renderAccount();
    renderPresets();
    renderProviders();
  } catch (error) {
    $("#profile-list").innerHTML =
      `<p class="privacy-note">画像加载失败：${escapeHtml(error.message)}</p>`;
  }

  $("#run-button").addEventListener("click", runFlow);
  $("#experiment-button").addEventListener("click", runExperiment);
  $("#register-button").addEventListener("click", registerAccount);
  $("#login-button").addEventListener("click", loginAccount);
  $("#logout-button").addEventListener("click", logoutAccount);
  $("#submit-survey-button").addEventListener("click", submitSurvey);
  $("#test-provider-button").addEventListener("click", testProvider);
  $("#toggle-key-button").addEventListener("click", () => {
    const input = $("#api-key-input");
    const reveal = input.type === "password";
    input.type = reveal ? "text" : "password";
    $("#toggle-key-button").textContent = reveal ? "隐藏" : "显示";
  });
  $$(".tab-button").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeTab = button.dataset.tab;
      renderResource();
    });
  });
  $$(".feedback-actions button").forEach((button) => {
    button.addEventListener("click", () => sendFeedback(button.dataset.feedback));
  });
  initializeSurveyInputs();
}

initialize();
