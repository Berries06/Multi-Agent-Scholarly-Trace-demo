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
  registrationOpen: false,
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
  $("#auth-view").hidden = authenticated;
  $("#app-view").hidden = !authenticated;
  $("#experiment-button").disabled =
    !authenticated || state.selectedProvider !== "mock";
  if (authenticated) {
    $("#account-status").textContent =
      `${state.user.nickname} · ${state.user.email} · 画像 v${state.user.profile_version}`;
    $("#profile-mode-note").textContent =
      "当前询问自动使用你的长期画像；后续修改会形成新版本，不覆盖历史实验。";
    $("#api-key-note").textContent =
      "已登录用户可直接选择「免费 DeepSeek (Flash)」，无需自备 Key。也可选择其他供应商并自填 Key。";
    $("#empty-state").hidden = Boolean(state.result);
    $("#result-content").hidden = !state.result;
    populateProfileEditor();
    renderProfiles();
  } else {
    state.result = null;
    $("#empty-state").hidden = true;
    $("#result-content").hidden = true;
    $("#api-key-note").textContent =
      "密钥仅经当前请求转发给所选供应商，不保存到本站、浏览器存储或日志。";
  }
}

function splitProfileTerms(value) {
  return String(value)
    .split(/[,，;；]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function profileEditorPayload() {
  const interests = splitProfileTerms($("#profile-interests").value);
  return {
    name: state.user?.nickname || state.user?.profile?.name || "学习者",
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
        email: $("#register-email").value.trim(),
        nickname: $("#register-nickname").value.trim(),
        password: $("#register-password").value,
      }),
    });
    state.user = payload.user;
    setAccountMessage("");
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
        identifier: $("#login-identifier").value.trim(),
        password: $("#login-password").value,
      }),
    });
    state.user = payload.user;
    setAccountMessage("");
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
    showAuthMode("login");
    renderAccount();
  } catch (error) {
    setAccountMessage(`退出失败：${error.message}`, true);
  }
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
  window.setTimeout(() => focusTarget.focus(), 0);
}

function populateProfileEditor() {
  if (!state.user) return;
  const profile = state.user.profile;
  $("#profile-education").value =
    profile.education === "未填写" ? "" : profile.education;
  $("#profile-role").value =
    profile.role === "学习者" ? "" : profile.role;
  $("#profile-goal").value = profile.goal || "";
  $("#profile-interests").value = (profile.interests || []).join("，");
  $("#profile-style").value = profile.preferred_style || "";
  $("#profile-difficulty").value = String(profile.expected_difficulty || 3);
}

async function saveProfile() {
  if (!state.user) return;
  const button = $("#save-profile-button");
  button.disabled = true;
  const status = $("#profile-save-status");
  try {
    const payload = await requestJson("/api/profile", {
      method: "PUT",
      body: JSON.stringify({ profile: profileEditorPayload() }),
    });
    state.user = payload.user;
    status.textContent = `画像 v${state.user.profile_version} 已保存。`;
    status.className = "provider-test-status success";
    renderAccount();
  } catch (error) {
    status.textContent = `保存失败：${error.message}`;
    status.className = "provider-test-status error";
  } finally {
    button.disabled = false;
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
      : "实时运行约 4 次模型调用；提交反馈会重新运行并产生新的用量。";
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
  const metrics = result.metrics || {};
  $("#metric-hallucination").textContent = percent(
    metrics.hallucination_proxy_rate,
  );
  $("#metric-adaptation").textContent = percent(metrics.adaptation_accuracy);
  $("#metric-coverage").textContent = percent(metrics.knowledge_coverage_rate);
  $("#metric-scope").textContent = metrics.metric_scope || "工程代理指标，待专家盲审。";
}
function renderQuality(result) {
  const assessment = result.quality_assessment || {};
  const scores = assessment.scores || {};
  $("#quality-gate-status").textContent = assessment.enforced
    ? `已准入 · ${assessment.counts?.accepted || 0} 条`
    : "消融模式 · 未执行准入";
  $("#quality-evidence").textContent = percent(scores.evidence_grounding || 0);
  $("#quality-profile").textContent = percent(scores.profile_fit || 0);
  $("#quality-feedback").textContent =
    scores.user_feedback == null ? "待填写" : percent(scores.user_feedback);
  $("#quality-overall").textContent = percent(scores.overall_quality || 0);
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
  const researchGaps = innovations.discovery?.research_gaps || [];
  $("#gap-summary").textContent = researchGaps.length
    ? `${researchGaps.length} 个`
    : "按需关闭";
  $("#probe-summary").textContent =
    result.provider_run?.mode === "live_llm"
      ? `${Number(result.provider_run.llm_duration_ms).toFixed(0)} ms`
      : result.performance?.total_ms == null
      ? "已关闭"
      : `${Number(result.performance.total_ms).toFixed(2)} ms`;

  const hypotheses = innovations.hypotheses || [];
  const hypothesisPanel = $("#hypothesis-panel");
  hypothesisPanel.hidden = hypotheses.length === 0;
  $("#hypothesis-ranking").innerHTML = hypotheses
    .map(
      (item) => {
        const score =
          item.score == null ? "待验证" : `${Math.round(item.score * 100)}分`;
        return `<li><b>#${item.rank} · ${score}</b>${escapeHtml(item.hypothesis)}</li>`;
      },
    )
    .join("");

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

  const sourceNames = {
    official_docs: "官方资料",
    openalex: "OpenAlex",
    crossref: "Crossref",
    arxiv: "arXiv",
    semantic_scholar: "Semantic Scholar",
    local_knowledge_base: "本地知识库",
    external: "外部检索源",
    multi_source: "多源检索",
  };
  const sourceCounts = run.source_counts || {};
  const sourceEntries = Object.entries(sourceCounts);
  const sourceCountBox = $("#provider-source-counts");
  sourceCountBox.hidden = sourceEntries.length === 0;
  sourceCountBox.innerHTML = sourceEntries.length
    ? `
      <div class="source-count-heading">
        <span>各来源初步返回</span>
        <small>去重筛选后入选 <b>${Number(run.selected_paper_count ?? result.papers?.length ?? 0)}</b> 篇</small>
      </div>
      <div class="source-count-list">
        ${sourceEntries
          .map(([source, count]) => {
            const numericCount = Number(count || 0);
            return `
              <span class="source-count-item ${numericCount === 0 ? "empty" : ""}">
                ${escapeHtml(sourceNames[source] || source)}
                <b>${numericCount}</b> 篇
              </span>
            `;
          })
          .join("")}
      </div>
    `
    : "";

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
    `${trace.length} 个基础 Agent · ${trace.reduce((sum, item) => sum + item.duration_ms, 0)} ms`;
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

function graphRelationLabel(value) {
  const labels = {
    evidence: "文献支持",
    contains: "包含证据句",
    support: "支持",
    contradict: "反驳",
    supports: "支持",
    requires: "需要",
    guides: "引导",
    guarantees: "保证",
    improves: "提升",
    enables: "促进",
    reduces: "降低",
    challenges: "质疑",
    extends: "扩展",
  };
  const raw = String(value || "关联");
  return labels[raw.toLowerCase()] || (/^[A-Za-z]/.test(raw) ? "关联" : raw);
}

function graphEvidenceText(span) {
  if (typeof span === "string") return span.trim();
  if (!span || typeof span !== "object") return "";
  return String(span.text || span.sentence || span.quote || span.span || "").trim();
}

function uniqueCriticismSentences(values) {
  const seen = new Set();
  const sentences = [];
  (values || []).forEach((value) => {
    const parts = String(value || "").match(/[^。！？!?]+[。！？!?]?/gu) || [];
    parts.forEach((part) => {
      const sentence = part.trim();
      const key = sentence.replace(/\s+/gu, "").replace(/[。！？!?]+$/u, "");
      if (!key || seen.has(key)) return;
      seen.add(key);
      sentences.push(/[。！？!?]$/u.test(sentence) ? sentence : `${sentence}。`);
    });
  });
  return sentences;
}

function renderGraph(graph) {
  const flowList = $("#evidence-flow-list");
  const detailPanel = $("#evidence-flow-detail");
  const allNodes = graph?.nodes || [];
  const relationEdges = (graph?.edges || [])
    .filter((edge) => edge.claim_id && !["rejected", "abstained"].includes(edge.status))
    .sort((left, right) => Number(right.confidence || 0) - Number(left.confidence || 0))
    .slice(0, 7);
  const nodeById = new Map(allNodes.map((node) => [node.id, node]));

  if (!relationEdges.length) {
    flowList.innerHTML = '<p class="flow-empty">本轮没有通过质量准入的中文知识关系。</p>';
    detailPanel.innerHTML = `
      <div class="flow-detail-empty">
        <span>等待证据</span>
        <strong>暂无可展示的论文结论</strong>
        <p>只有具备论文来源并通过质量检查的关系，才会进入这里。</p>
      </div>
    `;
    return;
  }

  flowList.innerHTML = relationEdges
    .map((edge, index) => {
      const source = nodeById.get(edge.source)?.label || edge.source;
      const target = nodeById.get(edge.target)?.label || edge.target;
      const relation = graphRelationLabel(edge.label);
      const confidence = Math.round(Number(edge.confidence || 0) * 100);
      const paperCount = (edge.evidence_titles || edge.evidence_ids || []).length;
      const status = edge.status === "review" ? "待复核" : "已通过";
      const flowWidth = 10 + Math.round(Math.max(0, Math.min(1, Number(edge.confidence || 0))) * 16);
      return `
        <button
          class="evidence-flow-lane ${index === 0 ? "active" : ""} ${escapeHtml(edge.status || "accepted")}"
          data-flow-index="${index}"
          type="button"
          role="listitem"
          aria-pressed="${index === 0 ? "true" : "false"}"
          aria-label="${escapeHtml(`${source}${relation}${target}，可信度${confidence}%`)}"
          style="--flow-width: ${flowWidth}px; --flow-opacity: ${(0.52 + confidence / 220).toFixed(2)}"
        >
          <span class="flow-concept flow-source">
            <small>方法 ${String(index + 1).padStart(2, "0")}</small>
            <strong>${escapeHtml(source)}</strong>
          </span>
          <span class="flow-channel">
            <span class="flow-river" aria-hidden="true"></span>
            <span class="flow-pulse" aria-hidden="true"></span>
            <span class="flow-relation">
              <strong>${escapeHtml(relation)}</strong>
              <small>${confidence}% · ${paperCount} 篇论文</small>
            </span>
          </span>
          <span class="flow-concept flow-target">
            <small>${status}</small>
            <strong>${escapeHtml(target)}</strong>
          </span>
        </button>
      `;
    })
    .join("");

  const renderFlowDetail = (index) => {
    const edge = relationEdges[index];
    if (!edge) return;
    const source = nodeById.get(edge.source)?.label || edge.source;
    const target = nodeById.get(edge.target)?.label || edge.target;
    const relation = graphRelationLabel(edge.label);
    const confidence = Math.round(Number(edge.confidence || 0) * 100);
    const papers = (edge.evidence_titles || edge.evidence_ids || []).slice(0, 3);
    const evidenceText = (edge.evidence_spans || [])
      .map(graphEvidenceText)
      .filter(Boolean)
      .slice(0, 1);
    const criticisms = uniqueCriticismSentences(edge.criticisms).slice(0, 2);
    const status = edge.status === "review" ? "待复核" : "已通过质量准入";

    detailPanel.innerHTML = `
      <div class="flow-detail-topline">
        <span>${status}</span>
        <strong>${confidence}<small>%</small></strong>
      </div>
      <p class="flow-detail-caption">当前证据流</p>
      <h3>
        <span>${escapeHtml(source)}</span>
        <em>${escapeHtml(relation)}</em>
        <span>${escapeHtml(target)}</span>
      </h3>
      <div class="flow-confidence" aria-label="可信度 ${confidence}%">
        <i style="width: ${confidence}%"></i>
      </div>
      <section class="flow-detail-section">
        <h4>论文依据 · ${papers.length} 篇</h4>
        ${papers.length
          ? `<ol>${papers.map((paper) => `<li>${escapeHtml(paper)}</li>`).join("")}</ol>`
          : "<p>暂无可追溯论文。</p>"}
      </section>
      ${evidenceText.length
        ? `<blockquote>${escapeHtml(evidenceText[0])}</blockquote>`
        : ""}
      <section class="flow-detail-section flow-quality-note">
        <h4>质量检查</h4>
        <p>${escapeHtml(criticisms[0] || "证据与命题结构一致，未发现阻断性问题。")}</p>
      </section>
      <p class="flow-detail-tip">点击左侧任意一条证据流，可查看对应论文来源。</p>
    `;

    $$(".evidence-flow-lane").forEach((lane, laneIndex) => {
      const active = laneIndex === index;
      lane.classList.toggle("active", active);
      lane.setAttribute("aria-pressed", String(active));
    });
  };

  $$(".evidence-flow-lane").forEach((lane) => {
    lane.addEventListener("click", () => renderFlowDetail(Number(lane.dataset.flowIndex)));
  });
  renderFlowDetail(0);
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
      const criticism = uniqueCriticismSentences(claim.criticisms)
        .slice(0, 2)
        .map(escapeHtml)
        .join("<br />") || "未发现阻断性问题。";
      const label = {
        accepted: "通过",
        review: "复核",
        rejected: "拒绝",
        abstained: "拒答",
      }[claim.status];
      return `
        <tr>
          <td>
            <span class="claim-main">${escapeHtml(claim.source)} ${escapeHtml(graphRelationLabel(claim.relation))} ${escapeHtml(claim.target)}</span>
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
  const blueOcean = resources.blue_ocean || {};
  $("#blue-ocean-panel").hidden = !blueOcean.enabled;
  $("#blue-ocean-hypothesis").textContent = blueOcean.hypothesis || "";
  $("#blue-ocean-caveat").textContent = blueOcean.caveat || "";
}

function renderQuestionnaire(result) {
  const form = result.resources?.feedback_form;
  const container = $("#feedback-questionnaire");
  if (!form) {
    container.innerHTML = "<p>当前结果没有反馈问卷。</p>";
    return;
  }
  const fields = (form.items || [])
    .map(
      (item) => `
        <label>
          <span>${escapeHtml(item.label)}</span>
          <select data-questionnaire="${escapeHtml(item.id)}">
            ${[1, 2, 3, 4, 5]
              .map((score) => `<option value="${score}" ${score === 3 ? "selected" : ""}>${score}</option>`)
              .join("")}
          </select>
        </label>
      `,
    )
    .join("");
  const concept = form.concept_feedback?.concept;
  const conceptField = concept
    ? `
      <label>
        <span>${escapeHtml(concept)} · 掌握程度自评</span>
        <select id="concept-self-rating" data-concept="${escapeHtml(concept)}">
          ${[1, 2, 3, 4, 5]
            .map((score) => `<option value="${score}" ${score === 3 ? "selected" : ""}>${score}</option>`)
            .join("")}
        </select>
      </label>
    `
    : "";
  container.innerHTML = `${fields}${conceptField}<small>${escapeHtml(form.note || "")}</small>`;
}

function collectQuestionnaire() {
  return Object.fromEntries(
    $$('[data-questionnaire]').map((field) => [
      field.dataset.questionnaire,
      Number(field.value),
    ]),
  );
}

function collectConceptFeedback() {
  const field = $("#concept-self-rating");
  if (!field?.dataset.concept) return {};
  return {
    [field.dataset.concept]: { self_rating: Number(field.value) },
  };
}
function renderResult(result) {
  state.result = result;
  $("#empty-state").hidden = true;
  $("#result-content").hidden = false;
  renderMetrics(result);
  renderQuality(result);
  renderProviderRun(result);
  renderInnovations(result);
  renderTrace(result);
  renderGraph(result.graph);
  renderReport(result);
  renderClaims(result);
  renderResource();
  renderQuestionnaire(result);
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

const RUN_PROGRESS_STAGES = [
  {
    percent: 10,
    label: "准备画像与任务",
    note: "正在读取学习目标、知识水平和本轮研究问题。",
  },
  {
    percent: 28,
    label: "检索论文证据",
    note: "正在检索开放论文来源；离线模式读取本地知识库。",
  },
  {
    percent: 52,
    label: "解析知识关系",
    note: "正在提取中文知识概念并组织论文证据流。",
  },
  {
    percent: 74,
    label: "执行质量检查",
    note: "正在核对来源、批判意见和知识准入条件。",
  },
  {
    percent: 90,
    label: "生成个性化资源",
    note: "正在生成学习路径、导读、实操和测评内容。",
  },
];

function setRunProgress(progress, status = "running") {
  const panel = $("#run-progress");
  const value = Math.max(0, Math.min(100, Number(progress.percent || 0)));
  panel.hidden = false;
  panel.className = `run-progress ${status}`;
  $("#run-progress-stage").textContent = progress.label;
  $("#run-progress-percent").textContent = `${Math.round(value)}%`;
  $("#run-progress-note").textContent = progress.note;
  $("#run-progress-bar").style.width = `${value}%`;
  $("#run-progress-track").setAttribute("aria-valuenow", String(Math.round(value)));
}

function beginRunProgress() {
  let stageIndex = 0;
  const stageDelay = state.selectedProvider === "mock" ? 180 : 1600;
  const minimumDuration = state.selectedProvider === "mock" ? 1050 : 0;
  setRunProgress(RUN_PROGRESS_STAGES[stageIndex]);
  const timer = window.setInterval(() => {
    if (stageIndex >= RUN_PROGRESS_STAGES.length - 1) return;
    stageIndex += 1;
    setRunProgress(RUN_PROGRESS_STAGES[stageIndex]);
  }, stageDelay);
  return {
    minimumWait: new Promise((resolve) => window.setTimeout(resolve, minimumDuration)),
    complete() {
      window.clearInterval(timer);
      setRunProgress(
        {
          percent: 100,
          label: "本轮任务已完成",
          note: "完整结果已返回，可以查看证据流、质量意见和个性化资源。",
        },
        "completed",
      );
    },
    fail() {
      window.clearInterval(timer);
      const current = Number($("#run-progress-track").getAttribute("aria-valuenow") || 0);
      setRunProgress(
        {
          percent: current,
          label: "本轮任务未完成",
          note: "运行过程中出现错误，请检查连接或配置后重试。",
        },
        "failed",
      );
    },
  };
}

async function runFlow() {
  if (!state.user) {
    window.alert("请先注册或登录后使用。");
    return;
  }
  const button = $("#run-button");
  const original = button.innerHTML;
  const progress = beginRunProgress();
  button.disabled = true;
  button.innerHTML = "<span>智能体协同中…</span><span>•••</span>";
  try {
    const request = requestJson("/api/run", {
      method: "POST",
      body: JSON.stringify({
        query: $("#research-query").value.trim(),
        preset: state.selectedPreset,
        llm: llmPayload(),
      }),
    });
    const [result] = await Promise.all([request, progress.minimumWait]);
    progress.complete();
    renderResult(result);
    $("#result-content").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    progress.fail();
    window.alert(`运行失败：${error.message}`);
  } finally {
    button.disabled = false;
    button.innerHTML = original;
  }
}
<<<<<<< Updated upstream

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

=======
>>>>>>> Stashed changes
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
        prior_knowledge_state: state.result.report?.knowledge_state || {},
        questionnaire: collectQuestionnaire(),
        concept_feedback: collectConceptFeedback(),
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
      authStatusPayload,
      libraryPayload,
    ] = await Promise.all([
      requestJson("/api/profiles"),
      requestJson("/api/configs"),
      requestJson("/api/providers"),
      requestJson("/api/auth/me"),
      requestJson("/api/auth/status"),
      requestJson("/api/library/slices"),
    ]);
    state.profiles = profilePayload.profiles;
    state.presets = configPayload.presets;
    state.selectedPreset = configPayload.default_demo_preset;
    state.providers = providerPayload.providers;
    state.selectedProvider = providerPayload.default_provider;
    state.user = authPayload.user;
    state.registrationOpen = Boolean(authStatusPayload.registration_open);
    $("#show-register-button").disabled = !state.registrationOpen;
    $("#registration-status").textContent = state.registrationOpen
      ? "注册只需要邮箱、昵称和密码，详细学习画像可在登录后完善。"
      : "当前暂未开放新账号注册，已有用户仍可正常登录。";
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
  $("#register-form").addEventListener("submit", (event) => {
    event.preventDefault();
    registerAccount();
  });
  $("#login-form").addEventListener("submit", (event) => {
    event.preventDefault();
    loginAccount();
  });
  $("#show-login-button").addEventListener("click", () => showAuthMode("login"));
  $("#show-register-button").addEventListener("click", () => {
    if (state.registrationOpen) showAuthMode("register");
  });
  $("#logout-button").addEventListener("click", logoutAccount);
  $("#save-profile-button").addEventListener("click", saveProfile);
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
  showAuthMode("login");
}

initialize();
