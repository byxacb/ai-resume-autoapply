from pathlib import Path
p = Path('/Users/bianyawen/WorkBuddy/2026-08-06-22-17-40/ai-resume-integration/ai-resume-autoapply/web/static/app.js')
text = p.read_text(encoding='utf-8')
addition = '''
let ws = null;
let paused = false;
function connectLogs() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(proto + '://' + location.host + '/ws/logs');
  ws.onmessage = (ev) => {
    if (paused) return;
    let msg;
    try { msg = JSON.parse(ev.data); } catch { msg = { level: 'info', message: ev.data }; }
    const el = document.getElementById('logs');
    if (!el) return;
    const line = document.createElement('div');
    line.className = 'log-line ' + (msg.level || 'info');
    const time = document.createElement('span');
    time.className = 'ts';
    time.textContent = new Date().toLocaleTimeString();
    line.appendChild(time);
    line.appendChild(document.createTextNode(' ' + (msg.message || '')));
    el.appendChild(line);
    el.scrollTop = el.scrollHeight;
    if (el.children.length > 500) el.removeChild(el.firstChild);
  };
  ws.onclose = () => setTimeout(connectLogs, 2000);
}
function toggleLogsPause() {
  paused = !paused;
  document.getElementById('btn-pause-logs')?.classList.toggle('paused', paused);
}
function clearLogs() {
  document.getElementById('logs') && (document.getElementById('logs').innerHTML = '');
}
setTimeout(connectLogs, 500);
'''
if 'function connectLogs' not in text:
    p.write_text(text + addition, encoding='utf-8')
