from pathlib import Path
p = Path('/Users/bianyawen/WorkBuddy/2026-08-06-22-17-40/ai-resume-integration/ai-resume-autoapply/orchestrator/api.py')
text = p.read_text(encoding='utf-8')
start = text.find('@app.post("/boss/apply")')
end = text.find('if __name__ == "__main__":')
if start < 0 or end < 0:
  raise SystemExit('markers not found')
prefix = text[:start]
suffix = text[end:]
new = prefix + (Path('.tmp_new_boss.txt').read_text(encoding='utf-8') if Path('.tmp_new_boss.txt').exists() else '') + suffix
p.write_text(new, encoding='utf-8')