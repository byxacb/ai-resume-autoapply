from pathlib import Path
p = Path('/Users/bianyawen/WorkBuddy/2026-08-06-22-17-40/ai-resume-integration/ai-resume-autoapply/web/static/app.js')
text = p.read_text(encoding='utf-8')

tab_logic = '''
// === Tab Switching ===
function switchTab(tabName) {
  document.querySelectorAll('.tab-pane').forEach(pane => pane.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
  const targetPane = document.getElementById('tab-' + tabName);
  if (targetPane) targetPane.classList.add('active');
  const tabBtn = document.querySelector('.tab[data-tab="' + tabName + '"]');
  if (tabBtn) tabBtn.classList.add('active');
}
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    const name = tab.getAttribute('data-tab');
    if (name) switchTab(name);
  });
});
'''

if 'function switchTab' not in text:
    p.write_text(text + tab_logic, encoding='utf-8')

# Fix e2e selector
e2e = Path('/Users/bianyawen/WorkBuddy/2026-08-06-22-17-40/ai-resume-integration/ai-resume-autoapply/e2e_playwright.py').read_text(encoding='utf-8')
if '#boss-job-id-v2, #boss-apply-form-v2' in e2e:
    e2e = e2e.replace('#boss-job-id-v2, #boss-apply-form-v2', '#boss-job-id-v2')
    Path('/Users/bianyawen/WorkBuddy/2026-08-06-22-17-40/ai-resume-integration/ai-resume-autoapply/e2e_playwright.py').write_text(e2e, encoding='utf-8')
