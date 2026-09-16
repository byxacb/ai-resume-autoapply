
import os
repo = '/Users/bianyawen/WorkBuddy/2026-08-06-22-17-40/ai-resume-integration/ai-resume-autoapply'
js_path = os.path.join(repo, 'web/static/app.js')
html_path = os.path.join(repo, 'web/templates/index.html')

with open(js_path, 'r', encoding='utf-8') as f:
    js = f.read()

if 'function showToast' not in js:
    js += '''
function showToast(message, kind='info') {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    Object.assign(container.style, {
      position: 'fixed', top: '16px', right: '16px', zIndex: '999',
      display: 'flex', flexDirection: 'column', gap: '8px'
    });
    document.body.appendChild(container);
  }
  const el = document.createElement('div');
  const colors = {
    info: '#3b82f6', success: '#10b981', warn: '#f59e0b', error: '#ef4444'
  };
  Object.assign(el.style, {
    background: colors[kind] || colors.info,
    color: 'white',
    padding: '10px 14px',
    borderRadius: '8px',
    fontSize: '13px',
    boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
    minWidth: '240px',
    opacity: '0',
    transform: 'translateY(-8px)',
    transition: 'all .2s ease'
  });
  el.textContent = message;
  container.appendChild(el);
  requestAnimationFrame(() => { el.style.opacity = '1'; el.style.transform = 'translateY(0)'; });
  setTimeout(() => {
    el.style.opacity = '0';
    el.style.transform = 'translateY(-8px)';
    setTimeout(() => el.remove(), 200);
  }, 2400);
}

const bossHandler = ''' + """document.getElementById("boss-apply-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const bossJobId = document.getElementById('boss-job-id')?.value?.trim() || '';
  const jdText = document.getElementById('boss-jd-text')?.value?.trim() || '';
  const candidateId = document.getElementById('boss-candidate')?.value;
  if (!bossJobId && !jdText) { showToast("请输入 BOSS Job ID 或 JD 文本", "warn"); return; }
  try {
    const candResp = await api('/candidates');
    const cand = (candResp.candidates || []).find(c => c.id === candidateId);
    const candidate = cand ? { name: cand.name, title: cand.title, years: cand.years } : { name: '求职者', title: '', years: 0 };
    const payload = { boss_job_id: bossJobId, jd_text: jdText, candidate, resume_path: cand?.resume_path || '', max_jobs: 1 };
    const res = await api('/boss/apply', { method: 'POST', body: JSON.stringify(payload) });
    showToast('投递任务已进入队列：run_id=' + res.run_id, 'success');
    refreshQueue();
  } catch (e) {
    showToast('投递失败：' + e.message, 'error');
  }
});""" + '''
setTimeout(loadBossCandidates, 500);
'''
js = js.replace(/document\.getElementById\("boss-apply-form"\)\?\.addEventListener\("submit",[\s\S]*?setTimeout\(loadBossCandidates, 500\);
/, bossHandler)

with open(js_path, 'w', encoding='utf-8') as f:
    f.write(js)

with open(html_path, 'r', encoding='utf-8') as f:
    html = f.read()
if 'toast-container' not in html:
    html = html.replace('</body>', '<div id="toast-container"></div>\n</body>')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
