const state = { jobs: [], selectedJobId: null, apiKey: sessionStorage.getItem("aivs-api-key") || "" };

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

function formatDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "medium" }).format(new Date(value));
}

function statusLabel(status) {
  return { queued: "排队中", running: "运行中", succeeded: "已完成", failed: "失败" }[status] || status;
}

function progressStageLabel(stage) {
  return {
    queued: "等待调度", planning: "规划中", narration: "配音中", video: "分镜生成中",
    composition: "合成中", social_drafts: "生成社交草稿", completed: "已完成", failed: "失败",
  }[stage] || stage || "等待中";
}

function renderProgress(progress) {
  const current = progress || { percent: 0, stage: "queued", completed_shots: 0, total_shots: 0, current_shot: 0, message: "" };
  const shotText = current.total_shots ? ` · Shot ${current.current_shot || current.completed_shots}/${current.total_shots}` : "";
  return `<div class="progress-line"><div class="progress-track"><span style="width:${Math.max(0, Math.min(100, Number(current.percent) || 0))}%"></span></div><strong>${Number(current.percent) || 0}%</strong></div><small>${escapeHtml(progressStageLabel(current.stage))}${shotText ? escapeHtml(shotText) : ""}${current.message ? ` · ${escapeHtml(current.message)}` : ""}</small>`;
}

function requestHeaders(extra = {}) {
  const headers = { "content-type": "application/json", ...extra };
  if (state.apiKey) headers.Authorization = `Bearer ${state.apiKey}`;
  return headers;
}

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: requestHeaders(options.headers || {}) });
  if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`);
  return response.status === 204 ? null : response.json();
}

function renderMetrics(stats) {
  $("metric-queued").textContent = stats.queued;
  $("metric-running").textContent = stats.running;
  $("metric-succeeded").textContent = stats.succeeded;
  $("metric-failed").textContent = stats.failed;
  $("metric-depth").textContent = stats.queue_depth;
}

function renderUsage(usage) {
  $("metric-duration").textContent = `${Math.round(usage.total_duration_seconds / 60)}m`;
}

function renderProviders(providers) {
  $("providers").innerHTML = providers.map((provider) => `
    <div class="provider-row">
      <div><strong>${escapeHtml(provider.provider_id)}</strong><span>${escapeHtml(provider.kind)}</span></div>
      <div class="provider-capabilities">${provider.capabilities.map(escapeHtml).join(" · ")}</div>
      <span class="status-dot ${provider.configured ? "on" : "off"}">${provider.configured ? "ready" : "off"}</span>
    </div>`).join("") || '<p class="muted">暂无 Provider</p>';
}

function renderBrandPresets(presets) {
  const select = $("brand-preset");
  const current = select.value;
  select.innerHTML = '<option value="">使用模板默认</option>' + presets.map((preset) => `<option value="${escapeHtml(preset.brand_preset_id)}">${escapeHtml(preset.name)} · v${preset.version}</option>`).join("");
  if (presets.some((preset) => preset.brand_preset_id === current)) select.value = current;
}

function renderJobs() {
  const filter = $("status-filter").value;
  const jobs = filter ? state.jobs.filter((job) => job.status === filter) : state.jobs;
  $("jobs").innerHTML = jobs.length ? jobs.map((job) => `
    <tr class="job-row" data-job-id="${escapeHtml(job.job_id)}">
      <td><strong>${escapeHtml(job.request.topic)}</strong><small>${escapeHtml(job.request.language)} · ${job.request.duration_seconds}s</small></td>
      <td><span class="status ${escapeHtml(job.status)}">${statusLabel(job.status)}</span></td>
      <td class="progress-cell">${renderProgress(job.progress)}</td>
      <td>${job.attempt}/${job.max_attempts}</td>
      <td>${formatDate(job.updated_at)}</td>
      <td><button class="link-button" data-open-job="${escapeHtml(job.job_id)}" type="button">查看</button></td>
    </tr>`).join("") : '<tr><td colspan="6" class="empty">暂无任务</td></tr>';
  document.querySelectorAll("[data-open-job]").forEach((button) => button.addEventListener("click", () => openDetail(button.dataset.openJob)));
}

const approvalPlatforms = [
  ["blog", "Blog"], ["wechat", "微信"], ["zhihu", "知乎"], ["bilibili", "B站"],
  ["xiaohongshu", "小红书"], ["douyin", "抖音"], ["podcast", "播客"],
];

function renderApprovals(approvals) {
  const latest = Object.fromEntries(approvals.map((item) => [item.platform, item]));
  $("approvals").innerHTML = approvalPlatforms.map(([platform, label]) => {
    const current = latest[platform];
    const decision = current?.decision || "pending";
    const decisionLabel = { approved: "已通过", rejected: "已驳回", pending: "待审核" }[decision];
    return `<div class="approval-row"><div><strong>${label}</strong><small>${decisionLabel}${current?.reviewer ? ` · ${escapeHtml(current.reviewer)}` : ""}</small></div><div class="approval-actions"><button class="button tiny" data-approval-platform="${platform}" data-approval-decision="approved" type="button">通过</button><button class="button tiny danger" data-approval-platform="${platform}" data-approval-decision="rejected" type="button">驳回</button><button class="button tiny" data-publish-platform="${platform}" data-publish-dry-run="true" type="button">预览</button>${decision === "approved" ? `<button class="button tiny" data-publish-platform="${platform}" data-publish-dry-run="false" type="button">发布</button>` : ""}</div></div>`;
  }).join("");
  document.querySelectorAll("[data-approval-platform]").forEach((button) => button.addEventListener("click", () => decideApproval(button.dataset.approvalPlatform, button.dataset.approvalDecision)));
  document.querySelectorAll("[data-publish-platform]").forEach((button) => button.addEventListener("click", () => publishDraft(button.dataset.publishPlatform, button.dataset.publishDryRun === "true")));
}

async function decideApproval(platform, decision) {
  const note = decision === "rejected" ? (window.prompt("驳回原因（可选）") || "") : "";
  try {
    await api(`/v1/jobs/${state.selectedJobId}/approvals`, { method: "POST", body: JSON.stringify({ platform, decision, reviewer: "dashboard-operator", note }) });
    await openDetail(state.selectedJobId);
  } catch (error) {
    $("form-message").textContent = `审批失败：${error.message}`;
  }
}

async function publishDraft(platform, dryRun) {
  if (!dryRun && !window.confirm("确认提交到已配置的外部发布 Provider？")) return;
  try {
    const result = await api(`/v1/jobs/${state.selectedJobId}/publish`, { method: "POST", body: JSON.stringify({ platform, dry_run: dryRun, actor: "dashboard-operator" }) });
    $("form-message").textContent = dryRun ? `预览完成：${result.message}` : `发布结果：${result.status}（${result.message}）`;
    await openDetail(state.selectedJobId);
  } catch (error) {
    $("form-message").textContent = `发布操作失败：${error.message}`;
  }
}

function renderPublishAudit(events) {
  $("publish-audit").innerHTML = events.length ? events.map((event) => `<li><span class="event-type">${escapeHtml(event.action)}</span><span>${escapeHtml(event.message)}</span><time>${formatDate(event.created_at)}</time></li>`).join("") : '<li class="muted">暂无发布审计记录</li>';
}

async function downloadArtifact(jobId, name) {
  try {
    const response = await fetch(`/v1/jobs/${jobId}/artifacts/${name}`, { headers: requestHeaders() });
    if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`);
    const link = document.createElement("a");
    link.href = URL.createObjectURL(await response.blob());
    link.download = name;
    link.click();
    URL.revokeObjectURL(link.href);
  } catch (error) {
    $("form-message").textContent = `下载失败：${error.message}`;
  }
}

async function openDetail(jobId) {
  state.selectedJobId = jobId;
  const [job, events] = await Promise.all([api(`/v1/jobs/${jobId}`), api(`/v1/jobs/${jobId}/events`)]);
  $("detail").classList.remove("hidden");
  $("detail-title").textContent = job.request.topic;
  $("detail-meta").innerHTML = `<span class="status ${escapeHtml(job.status)}">${statusLabel(job.status)}</span><span>尝试 ${job.attempt}/${job.max_attempts}</span><span>创建于 ${formatDate(job.created_at)}</span>${job.error_message ? `<span class="error-text">${escapeHtml(job.error_code)}: ${escapeHtml(job.error_message)}</span>` : ""}`;
  $("detail-progress").innerHTML = renderProgress(job.progress);
  $("events").innerHTML = events.map((event) => `<li><span class="event-type">${escapeHtml(event.event_type)}</span><span>${escapeHtml(event.message)}</span><time>${formatDate(event.created_at)}</time></li>`).join("") || '<li class="muted">暂无事件</li>';
  const artifactNames = [["video.mp4", "视频"], ["story-plan.json", "Story Plan"], ["subtitles.srt", "字幕"], ["narration.wav", "配音"], ["social-drafts.json", "社交草稿"]];
  $("artifacts").innerHTML = job.status === "succeeded" ? artifactNames.map(([name, label]) => `<button class="artifact" data-artifact-name="${name}" type="button">${label}<span>下载 ↗</span></button>`).join("") : '<p class="muted">任务成功后可下载产物</p>';
  document.querySelectorAll("[data-artifact-name]").forEach((button) => button.addEventListener("click", () => downloadArtifact(jobId, button.dataset.artifactName)));
  $("approvals").innerHTML = '<p class="muted">加载审批记录…</p>';
  if (job.status === "succeeded") {
    const [approvals, audit] = await Promise.all([api(`/v1/jobs/${jobId}/approvals`), api(`/v1/jobs/${jobId}/publish-audit`)]);
    renderApprovals(approvals);
    renderPublishAudit(audit);
  }
  else $("approvals").innerHTML = '<p class="muted">任务成功后可审核社交草稿</p>';
  $("detail").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function refresh() {
  try {
    const filter = $("status-filter").value;
    const [stats, usage, jobs, providers, brandPresets] = await Promise.all([
      api("/v1/stats"),
      api("/v1/usage"),
      api(`/v1/jobs?limit=100${filter ? `&status=${encodeURIComponent(filter)}` : ""}`),
      api("/v1/providers"),
      api("/v1/brand-presets"),
    ]);
    renderMetrics(stats);
    renderUsage(usage);
    state.jobs = jobs;
    renderJobs();
    renderProviders(providers.providers);
    renderBrandPresets(brandPresets);
    $("connection").textContent = "已连接";
    $("connection").className = "pill connected";
    if (state.selectedJobId) await openDetail(state.selectedJobId);
  } catch (error) {
    $("connection").textContent = "API 不可用";
    $("connection").className = "pill disconnected";
    $("form-message").textContent = error.message;
  }
}

$("job-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = $("form-message");
  message.textContent = "提交中…";
  const request = {
    topic: $("topic").value,
    source_markdown: $("source").value,
    duration_seconds: Number($("duration").value),
    language: $("language").value,
    voice: $("voice").value,
    brand_preset_id: $("brand-preset").value || null,
    use_ai: $("use-ai").checked,
  };
  try {
    const key = `dashboard-${crypto.randomUUID ? crypto.randomUUID() : Date.now()}`;
    const job = await api("/v1/jobs", { method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify(request) });
    message.textContent = `已加入任务 ${job.job_id}`;
    $("topic").value = "";
    await refresh();
    await openDetail(job.job_id);
  } catch (error) {
    message.textContent = `提交失败：${error.message}`;
  }
});

$("refresh").addEventListener("click", refresh);
$("api-key").value = state.apiKey;
$("save-api-key").addEventListener("click", () => {
  state.apiKey = $("api-key").value.trim();
  if (state.apiKey) sessionStorage.setItem("aivs-api-key", state.apiKey);
  else sessionStorage.removeItem("aivs-api-key");
  refresh();
});
$("status-filter").addEventListener("change", refresh);
$("close-detail").addEventListener("click", () => { state.selectedJobId = null; $("detail").classList.add("hidden"); });
refresh();
setInterval(refresh, 5000);
