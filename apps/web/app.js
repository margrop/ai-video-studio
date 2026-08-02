const state = { jobs: [], selectedJobId: null };

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

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "content-type": "application/json", ...(options.headers || {}) }, ...options });
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

function renderJobs() {
  const filter = $("status-filter").value;
  const jobs = filter ? state.jobs.filter((job) => job.status === filter) : state.jobs;
  $("jobs").innerHTML = jobs.length ? jobs.map((job) => `
    <tr class="job-row" data-job-id="${escapeHtml(job.job_id)}">
      <td><strong>${escapeHtml(job.request.topic)}</strong><small>${escapeHtml(job.request.language)} · ${job.request.duration_seconds}s</small></td>
      <td><span class="status ${escapeHtml(job.status)}">${statusLabel(job.status)}</span></td>
      <td>${job.attempt}/${job.max_attempts}</td>
      <td>${formatDate(job.updated_at)}</td>
      <td><button class="link-button" data-open-job="${escapeHtml(job.job_id)}" type="button">查看</button></td>
    </tr>`).join("") : '<tr><td colspan="5" class="empty">暂无任务</td></tr>';
  document.querySelectorAll("[data-open-job]").forEach((button) => button.addEventListener("click", () => openDetail(button.dataset.openJob)));
}

async function openDetail(jobId) {
  state.selectedJobId = jobId;
  const [job, events] = await Promise.all([api(`/v1/jobs/${jobId}`), api(`/v1/jobs/${jobId}/events`)]);
  $("detail").classList.remove("hidden");
  $("detail-title").textContent = job.request.topic;
  $("detail-meta").innerHTML = `<span class="status ${escapeHtml(job.status)}">${statusLabel(job.status)}</span><span>尝试 ${job.attempt}/${job.max_attempts}</span><span>创建于 ${formatDate(job.created_at)}</span>${job.error_message ? `<span class="error-text">${escapeHtml(job.error_code)}: ${escapeHtml(job.error_message)}</span>` : ""}`;
  $("events").innerHTML = events.map((event) => `<li><span class="event-type">${escapeHtml(event.event_type)}</span><span>${escapeHtml(event.message)}</span><time>${formatDate(event.created_at)}</time></li>`).join("") || '<li class="muted">暂无事件</li>';
  const artifactNames = [["video.mp4", "视频"], ["story-plan.json", "Story Plan"], ["subtitles.srt", "字幕"], ["narration.wav", "配音"]];
  $("artifacts").innerHTML = job.status === "succeeded" ? artifactNames.map(([name, label]) => `<a class="artifact" href="/v1/jobs/${jobId}/artifacts/${name}" target="_blank" rel="noreferrer">${label}<span>下载 ↗</span></a>`).join("") : '<p class="muted">任务成功后可下载产物</p>';
  $("detail").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function refresh() {
  try {
    const filter = $("status-filter").value;
    const [stats, usage, jobs, providers] = await Promise.all([
      api("/v1/stats"),
      api("/v1/usage"),
      api(`/v1/jobs?limit=100${filter ? `&status=${encodeURIComponent(filter)}` : ""}`),
      api("/v1/providers"),
    ]);
    renderMetrics(stats);
    renderUsage(usage);
    state.jobs = jobs;
    renderJobs();
    renderProviders(providers.providers);
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
$("status-filter").addEventListener("change", refresh);
$("close-detail").addEventListener("click", () => { state.selectedJobId = null; $("detail").classList.add("hidden"); });
refresh();
setInterval(refresh, 5000);
