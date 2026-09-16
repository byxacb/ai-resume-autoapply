// === AI 简历助手 Web 控制台 ===

const API = window.location.origin;
let ws = null;
let wsPaused = false;

// === Tabs ===
document.querySelectorAll('.tab').forEach(t => {
  t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    document.getElementById('tab-' + t.dataset.tab).classList.add('active');
    if (t.dataset.tab === 'dashboard') refreshAll();
    if (t.dataset.tab === 'queue') refreshQueue();
    if (t.dataset.tab === 'candidates') loadCandidates();
  });
});

// === Helpers ===
async function api(path, opts = {}) {
  const resp = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`HTTP ${resp.status}: ${text}`);
  }
  return resp.json();
}

function fmt(n) {
  return n === null || n === undefined ? '—' : n;
}

function scoreClass(score) {
  if (score >= 80) return 'score-high';
  if (score >= 60) return 'score-mid';
  return 'score-low';
}

function escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, c => ({
    '&': '&', '<': '<', '>': '>', '"': '"', "'": '"'
  }[c]));
}

// === Health & Config ===
async function refreshHealth() {
  try {
    const h = await api('/health');
    document.getElementById('health-status').textContent = '● 在线';
    document.getElementById('health-status').className = 'badge badge-ok';
    document.getElementById('cfg-min-score').textContent = h.min_match_score;
    document.getElementById('cfg-hour-cap').textContent = h.max_per_hour;
    document.getElementById('cfg-day-cap').textContent = h.max_per_day;
  } catch (e) {
    document.getElementById('health-status').textContent = '● 离线';
    document.getElementById('health-status').className = 'badge badge-err';
  }
}

// === KPI ===
async function refreshStats() {
  try {
    const data = await api('/stats');
    const q = data.queue || {};
    document.getElementById('kpi-pending').textContent = fmt(q.pending);
    document.getElementById('kpi-processing').textContent = fmt(q.processing);
    document.getElementById('kpi-completed').textContent = fmt(q.completed);
    document.getElementById('kpi-failed').textContent = fmt(q.failed);
    if (data.config) {
      if (data.config.min_match_score !== undefined) {
        document.getElementById('cfg-min-score').textContent = data.config.min_match_score;
      }
      if (data.config.max_per_hour !== undefined) {
        document.getElementById('cfg-hour-cap').textContent = data.config.max_per_hour;
      }
      if (data.config.max_per_day !== undefined) {
        document.getElementById('cfg-day-cap').textContent = data.config.max_per_day;
      }
    }
  } catch (e) {
    console.error(e);
  }
}

// === Recent Jobs ===
async function refreshRecent() {
  try {
    const data = await api('/jobs/recent?limit=20');
    const tbody = document.querySelector('#recent-table tbody');
    if (!data.jobs || data.jobs.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty">暂无已完成任务</td></tr>';
      return;
    }
    tbody.innerHTML = data.jobs.map(j => {
      const ats = j.ats_score || 0;
      const status = j.status || 'completed';
      const time = (j.completed_at || j.created_at || '').slice(11, 19);
      const jobJson = escapeHtml(JSON.stringify(j));
      return `<tr data-job="${jobJson}">
        <td>${escapeHtml(time)}</td>
        <td>${escapeHtml(j.company)}</td>
        <td>${escapeHtml(j.title)}</td>
        <td><span class="score-pill ${scoreClass(ats)}">${ats.toFixed(0)}</span></td>
        <td class="status-${status}">${escapeHtml(status)}</td>
      </tr>`;
    }).join('');
  } catch (e) {
    console.error(e);
  }
}

// === Candidates ===
async function loadCandidates() {
  try {
    const data = await api('/candidates');
    const tbody = document.querySelector('#candidates-table tbody');
    if (!data.candidates || data.candidates.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty">暂无候选人，请先创建</td></tr>';
    } else {
      tbody.innerHTML = data.candidates.map(c => `<tr>
        <td><code>${escapeHtml(c.id)}</code></td>
        <td>${escapeHtml(c.name)}</td>
        <td>${escapeHtml(c.title)}</td>
        <td>${c.years}</td>
        <td><small>${escapeHtml((c.resume_path || '').split('/').pop())}</small></td>
        <td>
          <button class="btn btn-sm" onclick="deleteCandidate('${c.id}')">删除</button>
        </td>
      </tr>`).join('');
    }
    // Populate select
    const select = document.getElementById('run-candidate');
    select.innerHTML = '<option value="">-- 选择候选人 --</option>' +
      (data.candidates || []).map(c =>
        `<option value="${c.id}">${escapeHtml(c.name)} (${escapeHtml(c.title)})</option>`
      ).join('');
  } catch (e) {
    console.error(e);
  }
}

async function deleteCandidate(id) {
  if (!confirm('确认删除此候选人？')) return;
  try {
    await api('/candidate/' + id, { method: 'DELETE' });
    loadCandidates();
  } catch (e) {
    alert('删除失败：' + e.message);
  }
}

function showCreateCandidate() {
  document.getElementById('candidate-modal').style.display = 'flex';
}
function closeModal() {
  document.getElementById('candidate-modal').style.display = 'none';
}

document.getElementById('candidate-form').addEventListener('submit', async e => {
  e.preventDefault();
  try {
    const name = document.getElementById('cand-name').value.trim();
    const title = document.getElementById('cand-title').value.trim();
    const years = parseInt(document.getElementById('cand-years').value) || 0;
    const skillsStr = document.getElementById('cand-skills').value.trim();
    const skills = skillsStr ? skillsStr.split(/[,，]/).map(s => s.trim()).filter(Boolean) : [];
    const resumeFile = document.getElementById('cand-resume').files[0];

    let resumePath = '';
    if (resumeFile) {
      const fd = new FormData();
      fd.append('file', resumeFile);
      const resp = await fetch(API + '/resume/upload', { method: 'POST', body: fd });
      if (!resp.ok) throw new Error('Upload failed');
      const data = await resp.json();
      resumePath = data.path;
    }

    await api('/candidate', {
      method: 'POST',
      body: JSON.stringify({ name, title, years, skills, resume_path: resumePath }),
    });

    closeModal();
    e.target.reset();
    loadCandidates();
    alert('候选人创建成功！');
  } catch (err) {
    alert('创建失败：' + err.message);
  }
});

// === Run ===
document.querySelectorAll('input[name="jd-source"]').forEach(r => {
  r.addEventListener('change', () => {
    document.getElementById('jd-upload-row').style.display = 'none';
    document.getElementById('jd-scrape-row').style.display = 'none';
    document.getElementById('jd-paste-row').style.display = 'none';
    document.getElementById('jd-' + r.value + '-row').style.display = 'block';
  });
});

document.getElementById('run-form').addEventListener('submit', async e => {
  e.preventDefault();
  const candidateId = document.getElementById('run-candidate').value;
  const source = document.querySelector('input[name="jd-source"]:checked').value;
  const max = parseInt(document.getElementById('run-max').value);
  const minScore = parseFloat(document.getElementById('run-min-score').value);

  // Get candidate
  const candResp = await api('/candidates');
  const cand = (candResp.candidates || []).find(c => c.id === candidateId);
  if (!cand) { alert('请选择候选人'); return; }

  let payload = {
    resume_path: cand.resume_path,
    candidate_name: cand.name,
    candidate_title: cand.title,
    candidate_years: cand.years,
    max_jobs: max,
    min_score: minScore,
  };

  try {
    if (source === 'upload') {
      const file = document.getElementById('jd-file').files[0];
      if (!file) { alert('请选择 JD 文件'); return; }
      const text = await file.text();
      payload.jd_list = JSON.parse(text);
    } else if (source === 'paste') {
      const text = document.getElementById('jd-paste').value.trim();
      if (!text) { alert('请粘贴 JD'); return; }
      payload.jd_list = JSON.parse(text);
    } else if (source === 'scrape') {
      const query = document.getElementById('scrape-query').value.trim();
      const city = document.getElementById('scrape-city').value;
      if (!query) { alert('请输入关键词'); return; }
      payload.scrape = { query, city, max_jobs: max };
    }

    showRunResult('⏳ 启动中...', 'info');
    const data = await api('/run', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    showRunResult(`✅ 任务已启动 (run_id=${data.run_id})。查看 <a href="#" onclick="document.querySelector('[data-tab=queue]').click()">队列</a> 页面跟踪进度。`, 'success');
    refreshAll();
  } catch (err) {
    showRunResult('❌ 启动失败：' + err.message, 'error');
  }
});

function showRunResult(msg, kind) {
  const el = document.getElementById('run-result');
  el.className = 'alert alert-' + kind;
  el.innerHTML = msg;
  el.style.display = 'block';
}

// === Queue ===
async function refreshQueue() {
  try {
    const data = await api('/queue/pending?limit=50');
    const tbody = document.querySelector('#queue-table tbody');
    if (!data.jobs || data.jobs.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty">队列为空</td></tr>';
      return;
    }
    tbody.innerHTML = data.jobs.map(j => {
      const ats = j.ats_score || 0;
      const jobJson = escapeHtml(JSON.stringify(j));
      return `<tr data-job="${jobJson}">
        <td><code>${escapeHtml((j.job_id || '').slice(-12))}</code></td>
        <td>${escapeHtml(j.company)}</td>
        <td>${escapeHtml(j.title)}</td>
        <td><span class="score-pill ${scoreClass(ats)}">${ats.toFixed(0)}</span></td>
        <td>${escapeHtml((j.created_at || '').slice(11, 19))}</td>
      </tr>`;
    }).join('');
  } catch (e) {
    console.error(e);
  }
}

// === Logs (WebSocket) ===
function appendLog(level, msg) {
  if (wsPaused) return;
  const div = document.getElementById('logs');
  const ts = new Date().toLocaleTimeString();
  div.innerHTML += `<div class="log-line ${level}"><span class="ts">${ts}</span>${escapeHtml(msg)}</div>`;
  div.scrollTop = div.scrollHeight;
}

function clearLogs() {
  document.getElementById('logs').innerHTML = '';
}

function toggleWS() {
  wsPaused = !wsPaused;
  document.getElementById('ws-toggle').textContent = wsPaused ? '▶️ 继续' : '⏸️ 暂停';
}

function connectWS() {
  const wsUrl = (window.location.protocol === 'https:' ? 'wss://' : 'ws://')
              + window.location.host + '/ws/logs';
  try {
    ws = new WebSocket(wsUrl);
    ws.onopen = () => appendLog('success', 'WebSocket 已连接');
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        appendLog(msg.level || 'info', msg.message || JSON.stringify(msg));
      } catch {
        appendLog('info', e.data);
      }
    };
    ws.onclose = () => {
      appendLog('warn', 'WebSocket 断开，5 秒后重连...');
      setTimeout(connectWS, 5000);
    };
    ws.onerror = () => appendLog('error', 'WebSocket 错误');
  } catch (e) {
    appendLog('error', '无法连接 WebSocket：' + e.message);
  }
}

// === Settings ===
async function loadSettings() {
  try {
    const stats = await api('/stats');
    document.getElementById('settings-json').textContent = JSON.stringify(stats, null, 2);
  } catch (e) {
    document.getElementById('settings-json').textContent = '加载失败：' + e.message;
  }
}

// === Refresh All ===
async function refreshAll() {
  await Promise.all([refreshHealth(), refreshStats(), refreshRecent()]);
}

// === Auto-refresh ===
setInterval(refreshAll, 5000);
setInterval(() => {
  if (document.querySelector('.tab[data-tab="queue"]').classList.contains('active')) refreshQueue();
}, 3000);

// === Init ===
refreshAll();
loadCandidates();
refreshQueue();
loadSettings();
connectWS();

// Show first log
appendLog('info', '控制台已启动。后端地址：' + API);
appendLog('info', 'Dashboard init complete');
console.log('[DEBUG] Dashboard loaded, API=', API);

// === Metrics Tab ===
function parsePrometheus(text) {
  const lines = text.split("\n");
  const res = {};
  for (const raw of lines) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const idx = line.indexOf(" ");
    if (idx < 0) continue;
    const name = line.slice(0, idx).split("{")[0];
    const num = Number(line.slice(idx + 1).trim());
    if (!Number.isNaN(num)) res[name] = num;
  }
  return res;
}

async function refreshMetrics() {
  try {
    const r = await fetch("/metrics");
    const text = await r.text();
    const data = parsePrometheus(text);
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v ?? "—"; };
    set("m-queue-size", data["ai_resume_queue_size"]);
    set("m-jobs-processed", data["ai_resume_jobs_processed_total"]);
    set("m-total-runs", data["ai_resume_runs_total"]);
    set("m-candidates", data["ai_resume_candidates_total"]);
    set("m-inflight", data["ai_resume_inflight_runs"]);
    set("m-llm-tokens", data["ai_resume_llm_tokens_total"]);
    const raw = document.getElementById("metrics-raw");
    if (raw) raw.textContent = text;
  } catch (e) { console.error(e); }
}

document.querySelectorAll(".tab").forEach(t => {
  t.addEventListener("click", () => { if (t.dataset.tab === "metrics") refreshMetrics(); });
});

// === Drag & Drop Upload ===
const uploadControllers = {};

function setupDropZone(zoneId, inputId, progressId, nameId, barId, cancelKey) {
  const zone = document.getElementById(zoneId);
  const input = document.getElementById(inputId);
  if (!zone || !input) return;

  zone.addEventListener("click", () => input.click());
  zone.addEventListener("dragover", e => { e.preventDefault(); zone.classList.add("dragover"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
  zone.addEventListener("drop", e => {
    e.preventDefault();
    zone.classList.remove("dragover");
    const files = e.dataTransfer.files;
    if (files.length) handleUpload(files[0], progressId, nameId, barId, cancelKey);
  });
  input.addEventListener("change", () => {
    if (input.files.length) handleUpload(input.files[0], progressId, nameId, barId, cancelKey);
    input.value = "";
  });
}

async function handleUpload(file, progressId, nameId, barId, cancelKey) {
  const progressEl = document.getElementById(progressId);
  const nameEl = document.getElementById(nameId);
  const barEl = document.getElementById(barId);
  if (progressEl) progressEl.style.display = "block";
  if (nameEl) nameEl.textContent = file.name;
  if (barEl) barEl.style.width = "0%";

  const controller = new AbortController();
  uploadControllers[cancelKey] = controller;

  const form = new FormData();
  form.append("file", file);

  try {
    const resp = await fetch("/resume/upload", {
      method: "POST",
      body: form,
      signal: controller.signal,
    });
    if (!resp.ok) throw new Error("Upload failed: " + resp.status);
    const data = await resp.json();
    if (barEl) barEl.style.width = "100%";
    // store path in hidden field if needed
    window.__lastUploadedResume = data.path;
    appendLog("success", "上传完成: " + file.name + " -> " + data.path);
  } catch (e) {
    if (e.name === "AbortError") {
      appendLog("warn", "上传已取消");
    } else {
      appendLog("error", "上传失败: " + e.message);
    }
  } finally {
    if (barEl) barEl.style.width = "0%";
    if (progressEl) progressEl.style.display = "none";
    delete uploadControllers[cancelKey];
  }
}

function cancelUpload(cancelKey) {
  const ctrl = uploadControllers[cancelKey];
  if (ctrl) ctrl.abort();
}

// Init drop zones
setupDropZone("cand-resume-drop", "cand-resume", "cand-resume-progress", "cand-resume-name", "cand-resume-bar", "cand");
setupDropZone("jd-file-drop", "jd-file", "jd-file-progress", "jd-file-name", "jd-file-bar", "jd");

// === Job Detail Modal ===
function openJobDetail(job) {
  const modal = document.getElementById("job-detail-modal");
  if (!modal || !job) return;
  document.getElementById("jd-modal-title").textContent = job.title || "职位详情";
  document.getElementById("jd-company").textContent = job.company || "—";
  document.getElementById("jd-title").textContent = job.title || "—";
  document.getElementById("jd-score").textContent = typeof job.ats_score === "number" ? job.ats_score.toFixed(0) : "—";
  document.getElementById("jd-status").textContent = job.status || "—";
  document.getElementById("jd-text").textContent = job.jd_text || job.description || "暂无";
  document.getElementById("jd-match").textContent = job.match_result ? JSON.stringify(job.match_result, null, 2) : "—";
  document.getElementById("jd-cover").textContent = job.cover_letter || "—";
  modal.style.display = "flex";
}
function closeJobDetail() {
  const modal = document.getElementById("job-detail-modal");
  if (modal) modal.style.display = "none";
}

// Wire table rows to open modal
function wireJobTable(tableId) {
  const table = document.getElementById(tableId);
  if (!table) return;
  table.addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-job]");
    if (!tr) return;
    try {
      const job = JSON.parse(tr.dataset.job);
      openJobDetail(job);
    } catch (err) { console.error(err); }
  });
}

.width || 300;
  canvas.height = 180;
  const w = canvas.width, h = canvas.height;
  const max = Math.max(...points.map(p => p.v)) || 1;
  ctx.clearRect(0,0,w,h);
  ctx.strokeStyle = "#4f46e5";
  ctx.lineWidth = 2;
  ctx.beginPath();
  const step = w / (points.length - 1 || 1);
  points.forEach((p, i) => {
    const x = i * step;
    const y = h - (p.v / max) * (h - 20) - 10;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.fillStyle = "#374151";
  ctx.font = "12px sans-serif";
  ctx.fillText(label + " (last " + points.length + " samples)", 8, 16);
}

// === Chart.js Metrics ===
let chartQueue = null;
let chartThroughput = null;

function ensureChart(id, label) {
  const el = document.getElementById(id);
  if (!el) return null;
  if (!window.Chart) return null;
  const ctx = el.getContext("2d");
  return new Chart(ctx, {
    type: "line",
    data: { labels: [], datasets: [{ label: label, data: [], borderColor: "#4f46e5", backgroundColor: "rgba(79,70,229,0.15)", fill: true, tension: 0.3, pointRadius: 2 }] },
    options: { responsive: true, maintainAspectRatio: false, scales: { x: { display: false }, y: { beginAtZero: false } }, plugins: { legend: { display: false } } }
  });
}

function updateChart(chart, label, value) {
  if (!chart) return;
  chart.data.labels.push(new Date().toLocaleTimeString());
  chart.data.datasets[0].data.push(value);
  if (chart.data.labels.length > 60) chart.data.labels.shift();
  if (chart.data.datasets[0].data.length > 60) chart.data.datasets[0].data.shift();
  chart.update("none");
}

async function refreshMetrics() {
  try {
    const r = await fetch("/metrics");
    const text = await r.text();
    const data = parsePrometheus(text);
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v ?? "—"; };
    set("m-queue-size", data["ai_resume_queue_size"]);
    set("m-jobs-processed", data["ai_resume_jobs_processed_total"]);
    set("m-total-runs", data["ai_resume_runs_total"]);
    set("m-candidates", data["ai_resume_candidates_total"]);
    set("m-inflight", data["ai_resume_inflight_runs"]);
    set("m-llm-tokens", data["ai_resume_llm_tokens_total"]);
    const raw = document.getElementById("metrics-raw");
    if (raw) raw.textContent = text;

    if (!chartQueue && window.Chart) chartQueue = ensureChart("chart-queue", "Queue size");
    if (!chartThroughput && window.Chart) chartThroughput = ensureChart("chart-throughput", "Jobs processed");
    updateChart(chartQueue, "Queue size", Number(data["ai_resume_queue_size"]) || 0);
    updateChart(chartThroughput, "Jobs processed", Number(data["ai_resume_jobs_processed_total"]) || 0);
  } catch (e) { console.error(e); }
}

async function submitBossApply() {
  const bossJobId = document.getElementById('boss-job-id')?.value?.trim() || '';
  const jdText = document.getElementById('boss-jd-text')?.value?.trim() || '';
  const candidateId = document.getElementById('run-candidate')?.value;
  if (!bossJobId && !jdText) { alert('请输入 BOSS 职位 ID 或 JD 文本'); return; }
  try {
    const candResp = await api('/candidates');
    const cand = (candResp.candidates || []).find(c => c.id === candidateId);
    const candidate = cand ? { name: cand.name, title: cand.title, years: cand.years, company: '' } : { name: '求职者', title: '', years: 0 };
    const payload = { boss_job_id: bossJobId, jd_text: jdText, candidate, resume_path: cand?.resume_path || '', max_jobs: 1 };
    const data = await api('/boss/apply', { method: 'POST', body: JSON.stringify(payload) });
    alert('投递任务已进入队列：run_id=' + data.run_id);
    refreshQueue();
  } catch (e) {
    alert('投递失败：' + e.message);
  }
}
document.getElementById('boss-apply-form')?.addEventListener('submit', (e) => { e.preventDefault(); submitBossApply(); });

async function submitBossApply() {
  const bossJobId = document.getElementById('boss-job-id')?.value?.trim() || '';
  const jdText = document.getElementById('boss-jd-text')?.value?.trim() || '';
  const candidateId = document.getElementById('run-candidate')?.value;
  if (!bossJobId && !jdText) { alert('请输入 BOSS 职位 ID 或 JD 文本'); return; }
  try {
    const candResp = await api('/candidates');
    const cand = (candResp.candidates || []).find(c => c.id === candidateId);
    const candidate = cand ? { name: cand.name, title: cand.title, years: cand.years, company: '' } : { name: '求职者', title: '', years: 0 };
    const payload = { boss_job_id: bossJobId, jd_text: jdText, candidate, resume_path: cand?.resume_path || '', max_jobs: 1 };
    const data = await api('/boss/apply', { method: 'POST', body: JSON.stringify(payload) });
    alert('投递任务已进入队列：run_id=' + data.run_id);
    refreshQueue();
  } catch (e) {
    alert('投递失败：' + e.message);
  }
}
document.getElementById('boss-apply-form')?.addEventListener('submit', (e) => { e.preventDefault(); submitBossApply(); });

function toggleTheme() {
  const html = document.documentElement;
  const current = html.getAttribute('data-theme');
  const next = current === 'dark' ? 'light' : 'dark';
  html.setAttribute('data-theme', next);
  localStorage.setItem('theme', next);
}
(function initTheme() {
  const saved = localStorage.getItem('theme');
  if (saved === 'dark') document.documentElement.setAttribute('data-theme', 'dark');
})();
window.__recentPage = 1;
window.__recentPageSize = 10;
window.__queuePage = 1;
window.__queuePageSize = 10;
function paginate(containerId, total, page, pageSize, renderFn) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  page = Math.min(page, totalPages);
  renderFn(page);
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = '';
  const prev = document.createElement('button');
  prev.textContent = '上一页';
  prev.disabled = page <= 1;
  prev.onclick = () => { if (page > 1) { window[containerId] = page - 1; refreshRecent(); if (containerId === 'queue-pagination') refreshQueue(); } };
  el.appendChild(prev);
  const info = document.createElement('span');
  info.style.margin = '0 8px';
  info.textContent = page + ' / ' + totalPages;
  el.appendChild(info);
  const next = document.createElement('button');
  next.textContent = '下一页';
  next.disabled = page >= totalPages;
  next.onclick = () => { if (page < totalPages) { window[containerId] = page + 1; refreshRecent(); if (containerId === 'queue-pagination') refreshQueue(); } };
  el.appendChild(next);
}
function renderRecentTable(jobs) {
  // existing logic will be wrapped by pagination in caller if needed
}
