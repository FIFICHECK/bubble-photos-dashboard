#!/usr/bin/env python3
"""
Bubble Photos Update v2 — Per-SKU scheduled photo swaps.
Checks config.json, determines which SKUs need photo updates based on start/end times.
"""
import os, sys, json, base64, time, re, requests
from datetime import datetime
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GITHUB_REPO = 'FIFICHECK/bubble-photos-dashboard'
GITHUB_BRANCH = 'master'
MMS_EMAIL = '***REDACTED***'
MMS_PASSWORD = '***REDACTED***!!!'
STORE_ID = 'B0961005'

def get_token():
    return os.environ.get('BUBBLE_PHOTOS_TOKEN', '')

GH_HEADERS = lambda: {'Authorization': f'token {get_token()}', 'Accept': 'application/vnd.github.v3+json'}
GH_API = f'https://api.github.com/repos/{GITHUB_REPO}'

def gh_get(path):
    r = requests.get(f'{GH_API}/{path}', headers=GH_HEADERS())
    r.raise_for_status()
    return r.json()

def gh_put(path, data, sha=None):
    payload = {
        'message': 'Auto-update via photos_update.py',
        'content': base64.b64encode(json.dumps(data, indent=2).encode()).decode(),
        'branch': GITHUB_BRANCH
    }
    if sha: payload['sha'] = sha
    r = requests.put(f'{GH_API}/{path}', headers=GH_HEADERS(), json=payload)
    r.raise_for_status()
    return r.json()

def get_config():
    try:
        info = gh_get('contents/config.json')
        config = json.loads(base64.b64decode(info['content']).decode())
        config['_sha'] = info['sha']
        return config
    except Exception as e:
        print(f'❌ Config fetch failed: {e}')
        sys.exit(1)

def get_dashboard_data():
    try:
        info = gh_get('contents/dashboard_data.json')
        d = json.loads(base64.b64decode(info['content']).decode())
        d['_sha'] = info['sha']
        return d
    except:
        return {'history': [], '_sha': None}

def save_json(path, data):
    sha = data.pop('_sha', None)
    gh_put(f'contents/{path}', data, sha)

# ========== MMS BROWSER ==========
class MMSUpdater:
    def __init__(self):
        self.pw = None
        self.browser = None
        self.page = None

    def start(self):
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(headless=True)
        self.page = self.browser.new_page()
        self.page.set_viewport_size({'width': 1920, 'height': 1080})

    def stop(self):
        try: self.browser.close()
        except: pass
        try: self.pw.stop()
        except: pass

    def login(self):
        print('  🔑 Login...')
        self.page.goto('https://merchant.shoalter.com/login', wait_until='networkidle')
        time.sleep(2)
        self.page.fill('input[placeholder="請輸入ID"]', MMS_EMAIL)
        self.page.fill('input[placeholder="請輸入密碼"]', MMS_PASSWORD)
        result = self.page.evaluate("""(e,p)=>{var f=document.querySelector('form');if(!f)return'no form';var k=Object.keys(f).find(k=>k.startsWith('__reactFiber'));if(!k)return'no fiber';var x=f[k],ok=false;while(x&&!ok){var m=x.memoizedProps;if(m&&typeof m==='object'&&m.onFinish){m.onFinish({account:e,password:p});ok=true;}x=x.return;}return ok?'ok':'nf';}""", MMS_EMAIL, MMS_PASSWORD)
        if result != 'ok': raise Exception(f'Login failed: {result}')
        time.sleep(3)
        if 'login' in self.page.url.lower(): raise Exception('Still on login page')
        print('  ✅ Logged in')

    def update_photo(self, sku, photo_url, action_label='start'):
        """Update the main photo for a SKU"""
        sku_id = sku.split('_S_')[-1] if '_S_' in sku else sku
        print(f'  📸 [{action_label}] {sku}...')
        try:
            self.page.goto('https://merchant.shoalter.com/product-management/product-list', wait_until='networkidle')
            time.sleep(2)
            inp = self.page.query_selector('input[placeholder="搜尋 SKU ID"]')
            if not inp: raise Exception('Search input not found')
            inp.fill('')
            inp.fill(sku_id)
            time.sleep(0.5)
            sb = self.page.query_selector('button:has-text("搜 索")')
            if sb: sb.click()
            else:
                for b in self.page.query_selector_all('button'):
                    if '搜' in (b.inner_text() or ''): b.click(); break
            time.sleep(3)
            # Get edit URL
            edit_url = self.page.evaluate("""(s)=>{var rows=document.querySelectorAll('tr.ant-table-row');for(var r of rows){var c=r.querySelectorAll('td');if(c.length>=4&&c[3]?.innerText?.trim()===s){var l=c[c.length-1]?.querySelector('a');if(l)return l.href;}}return null;}""", STORE_ID)
            if not edit_url: raise Exception(f'No row for store {STORE_ID}')
            self.page.goto(edit_url, wait_until='networkidle')
            time.sleep(3)
            # Delete existing photos
            self.page.evaluate("""()=>{var d=document.querySelectorAll('[class*=\"ant-upload-list-item\"] [class*=\"delete\"],[aria-label=\"delete\"],.anticon-delete');for(var b of d){var btn=b.closest('button')||b.parentElement;if(btn){btn.click();}}return true;}""")
            time.sleep(1)
            # Upload photo from URL
            result = self.page.evaluate("""async(u)=>{try{var r=await fetch(u);if(!r.ok)return'fetch fail:'+r.status;var b=await r.blob();var f=new File([b],'photo.jpg',{type:b.type||'image/jpeg'});var fi=document.querySelectorAll('input[type=\"file\"]');if(!fi||!fi[0])return'no input';var dt=new DataTransfer();dt.items.add(f);fi[0].files=dt.files;fi[0].dispatchEvent(new Event('change',{bubbles:true}));return'ok:'+f.size;}catch(e){return'err:'+e.message;}}""", photo_url)
            print(f'    Upload: {result}')
            if 'ok:' in result:
                time.sleep(2)
                # Click Done
                done = self.page.evaluate("""()=>{var b=document.querySelectorAll('button');for(var x of b){if(x.innerText.trim()==='完 成'){x.click();return true;}}return false;}""")
                print(f'    Done: {done}')
                time.sleep(3)
                return True
            return False
        except Exception as e:
            print(f'    ❌ {e}')
            return False

    def run(self, actions):
        """actions: list of (sku, photo_url, action_label)"""
        if not actions: return []
        self.start()
        results = []
        try:
            self.login()
            for sku, url, label in actions:
                ok = self.update_photo(sku, url, label)
                results.append({'sku': sku, 'action': label, 'success': ok})
                time.sleep(2)
        finally:
            self.stop()
        return results

# ========== MAIN ==========
def main():
    print('🖼️ Bubble Photos v2 — Checking schedules...')
    now = datetime.now()
    print(f'⏰ {now.isoformat()}')

    config = get_config()
    skus = config.get('skus', {})
    if not skus:
        print('✅ No SKUs configured')
        return

    # Determine what actions to take
    actions = []  # (sku, photo_url, label)
    for sku, entry in skus.items():
        status = entry.get('status', 'pending')
        start_time = entry.get('start_time', '')
        end_time = entry.get('end_time', '')
        start_url = entry.get('start_photo_url', '')
        end_url = entry.get('end_photo_url', '')

        # Skip if already completed
        if status == 'completed':
            print(f'  ⏭️ {sku}: already completed')
            continue

        # Check start time
        if status == 'pending' and start_time:
            try:
                st = datetime.fromisoformat(start_time)
                if now >= st:
                    if start_url:
                        print(f'  🟢 {sku}: START time reached')
                        actions.append((sku, start_url, 'start'))
                    else:
                        print(f'  ⚠️ {sku}: START time reached but no start_photo_url')
                else:
                    mins = int((st - now).total_seconds() / 60)
                    print(f'  ⏳ {sku}: Start in {mins} min')
            except Exception as e:
                print(f'  ⚠️ {sku}: bad start_time: {e}')

        # Check end time (only if active or we just processed start)
        if status == 'active' and end_time:
            try:
                et = datetime.fromisoformat(end_time)
                if now >= et:
                    if end_url:
                        print(f'  🔴 {sku}: END time reached, swapping photo')
                        actions.append((sku, end_url, 'end'))
                    else:
                        print(f'  ⚠️ {sku}: END time reached but no end_photo_url, marking completed')
                        # Mark completed even without end photo
                        skus[sku]['status'] = 'completed'
                        skus[sku]['last_updated'] = now.isoformat()
                else:
                    mins = int((et - now).total_seconds() / 60)
                    print(f'  🟢 {sku}: Active, end in {mins} min')
            except Exception as e:
                print(f'  ⚠️ {sku}: bad end_time: {e}')

    if not actions:
        # Still save any status changes (e.g. completed without end photo)
        if any(s.get('status') == 'completed' for s in skus.values()):
            config.pop('_sha', None)
            save_json('config.json', config)
            print('✅ Status updates saved')
        else:
            print('✅ No actions needed')
        return

    print(f'\n📦 {len(actions)} action(s) to process')

    # Run browser updates
    updater = MMSUpdater()
    results = updater.run(actions)

    # Update config + log
    dashboard = get_dashboard_data()
    if 'history' not in dashboard: dashboard['history'] = []

    for r in results:
        sku = r['sku']
        label = r['action']
        ok = r['success']

        if sku in skus:
            if ok:
                if label == 'start':
                    skus[sku]['status'] = 'active'
                    # Check if end time already passed
                    end_t = skus[sku].get('end_time', '')
                    if end_t:
                        try:
                            if datetime.fromisoformat(end_t) <= now:
                                skus[sku]['status'] = 'completed'
                        except: pass
                elif label == 'end':
                    skus[sku]['status'] = 'completed'
                skus[sku]['last_updated'] = now.isoformat()
            else:
                skus[sku]['status'] = 'failed'

        dashboard['history'].append({
            'sku': sku,
            'action': label,
            'photo': skus.get(sku, {}).get('end_photo_url' if label == 'end' else 'start_photo_url', ''),
            'status': 'success' if ok else 'failed',
            'time': now.isoformat()
        })

    # Trim history
    dashboard['history'] = dashboard['history'][-500:]

    # Save
    config.pop('_sha', None)
    save_json('config.json', config)
    save_json('dashboard_data.json', dashboard)
    print('✅ All saved!')

if __name__ == '__main__':
    main()
