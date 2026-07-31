#!/usr/bin/env python3
"""
Phase scheduler: check if any pending phase is within 15 min, then run photos_update.py.
Replaces the old every-5-min cron with targeted runs.
"""
import os, json, base64, requests, subprocess, sys
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GITHUB_REPO = 'FIFICHECK/bubble-photos-dashboard'
GITHUB_BRANCH = 'master'

def get_token():
    t = os.environ.get('BUBBLE_PHOTOS_TOKEN', '')
    if not t:
        with open(os.path.expanduser('~/.config/gh/hosts.yml')) as f:
            for line in f:
                if 'oauth_token' in line:
                    t = line.split(':')[1].strip()
    return t

tok = get_token()
headers = {'Authorization': f'token {tok}', 'Accept': 'application/vnd.github.v3+json'}

try:
    r = requests.get(f'https://api.github.com/repos/{GITHUB_REPO}/contents/config.json?ref={GITHUB_BRANCH}', headers=headers)
    r.raise_for_status()
    info = r.json()
    config = json.loads(base64.b64decode(info['content']).decode())
except Exception as e:
    print(f'❌ Config fetch: {e}', file=sys.stderr)
    sys.exit(1)

now = datetime.now()
should_run = False
reasons = []

for sku, entry in config.get('skus', {}).items():
    if entry.get('status') == 'completed':
        continue
    phases = entry.get('phases', [])
    cur = entry.get('current_phase', -1)
    for i in range(cur + 1, len(phases)):
        p = phases[i]
        t = p.get('time', '')
        if not t or not p.get('photo_url'):
            continue
        try:
            pt = datetime.fromisoformat(t)
            diff = (pt - now).total_seconds()
            if diff <= 900 and diff >= -900:  # within 15min before OR 15min after (photos_update runs when time has passed)
                should_run = True
                reasons.append(f'{sku} Phase {i+1} ({p.get("label","")}) at {t}')
            break  # only check next pending phase
        except:
            pass

if should_run:
    print(f'⏰ Phase due! {", ".join(reasons)}')
    run_script = os.path.join(BASE_DIR, 'photos_update.py')
    env = os.environ.copy()
    result = subprocess.run([sys.executable, run_script], capture_output=True, text=True, env=env)
    print(result.stdout)
    if result.stderr:
        print(f'⚠️ {result.stderr}', file=sys.stderr)
    print(f'✅ Exit: {result.returncode}')
else:
    # Silent — no output means no message sent (no_agent mode)
    pass
