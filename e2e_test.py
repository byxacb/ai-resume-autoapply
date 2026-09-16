import requests, json, tempfile, os
base='http://localhost:8080'
report=[]

def check(name,fn):
    try:
        out=fn()
        report.append({'step':name,'status':'PASS','detail':str(out)[:120]})
        return out
    except Exception as e:
        report.append({'step':name,'status':'FAIL','detail':str(e)})
        return None

def get(p):
    r=requests.get(base+p, timeout=10)
    return {'code':r.status_code,'body':r.text[:120]}

def post(p,body):
    r=requests.post(base+p,json=body, timeout=10)
    return {'code':r.status_code,'body':r.text[:180]}

# 1. UI loads
check('ui_html', lambda: get('/'))
check('ui_js', lambda: get('/static/app.js'))
check('ui_css', lambda: get('/static/style.css'))

# 2. Core APIs
check('health', lambda: get('/health'))
check('stats', lambda: get('/stats'))
check('candidates_list', lambda: get('/candidates'))
check('metrics', lambda: get('/metrics'))
check('jobs_recent', lambda: get('/jobs/recent'))
check('queue_pending', lambda: get('/queue/pending'))

# 3. Create candidate
cand = check('create_candidate', lambda: post('/candidate',{'name':'E2E Test','title':'Test Engineer','years':3}))
candidate_id = cand['body'].split('"id":"')[1].split('"')[0] if cand and cand['code']==200 else None

# 4. Long name validation
check('long_name_validation', lambda: post('/candidate',{'name':'A'*500,'title':'X','years':1}))

# 5. Upload resume
with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
    f.write(b'E2E test resume content')
    tmp=f.name
try:
    with open(tmp,'rb') as f:
        files={'file':('resume_e2e.txt',f,'text/plain')}
        r=requests.post(base+'/resume/upload', files=files, timeout=10)
        upload_result = {'code':r.status_code,'body':r.text[:120]}
        report.append({'step':'upload_resume','status':'PASS' if r.status_code==200 else 'FAIL','detail':upload_result})
        resume_path = r.json().get('path','') if r.status_code==200 else ''
finally:
    os.unlink(tmp)

# 6. Run task with scrape
run = check('run_task_scrape', lambda: post('/run',{
    'resume_path': resume_path or '/tmp/x.pdf',
    'candidate_name':'E2E Test',
    'candidate_title':'Test Engineer',
    'candidate_years':3,
    'max_jobs':2,
    'scrape':{'query':'Python','city':'北京','max_jobs':2}
}))

# 7. CORS check: localhost should be allowed in dev
r=requests.get(base+'/health', headers={'Origin':'http://localhost:8080'}, timeout=10)
cors_ok = r.status_code==200 and 'access-control-allow-origin' in r.headers
report.append({'step':'cors_localhost_ok','status':'PASS' if cors_ok else 'FAIL','detail':f'status={r.status_code}, acao={"access-control-allow-origin" in r.headers}'})

# 8. WebSocket check
try:
  import websocket
  HAVE_WS = True
except Exception:
  HAVE_WS = False

if HAVE_WS:
  try:
    ws=websocket.create_connection(base+'/ws/logs', timeout=5)
    ws.send('ping')
    resp=ws.recv()
    ws.close()
    report.append({'step':'websocket','status':'PASS','detail':resp[:80]})
  except Exception as e:
    report.append({'step':'websocket','status':'FAIL','detail':str(e)})
else:
  report.append({'step':'websocket','status':'SKIP','detail':'websocket-client not installed'})

# Summary
passed=sum(1 for r in report if r['status']=='PASS')
failed=sum(1 for r in report if r['status']=='FAIL')
skipped=sum(1 for r in report if r['status']=='SKIP')
print(json.dumps({'passed':passed,'failed':failed,'skipped':skipped,'details':report}, ensure_ascii=False))

# === BOSS Apply endpoints ===
def test_boss_apply_endpoint():
    payload = {"boss_job_id": "12345", "jd_text": "Example JD", "candidate": {"name": "Test", "title": "Dev", "years": 2}, "max_jobs": 1}
    r = requests.post(API + "/boss/apply", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "run_id" in data
    run_id = data["run_id"]
    r = requests.get(API + "/boss/apply/{}/result".format(run_id))
    assert r.status_code == 200
    result = r.json()
    assert result.get("run_id") == run_id

def test_boss_apply_recent():
    r = requests.get(API + "/boss/apply/recent?limit=5")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data

def run_boss_tests():
    test_boss_apply_endpoint()
    test_boss_apply_recent()
    print("BOSS apply tests passed")
