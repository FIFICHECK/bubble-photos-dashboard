#!/usr/bin/env python3
"""
Bubble Photos Update v3 — Per-SKU multi-phase photo swaps.
Each SKU has N phases with scheduled times. The script uploads each phase's photo when its time arrives.
"""
import os, sys, json, base64, time, re, requests
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GITHUB_REPO = 'FIFICHECK/bubble-photos-dashboard'
GITHUB_BRANCH = 'master'
MMS_EMAIL = '***REDACTED***'
MMS_PASSWORD = '***REDACTED***!!!'
STORE_ID = 'B0961005'

def get_token():
    return os.environ.get('BUBBLE_PHOTOS_TOKEN', '')
def gh_hdrs():
    return {'Authorization': f'token {get_token()}', 'Accept': 'application/vnd.github.v3+json'}
GH_API = f'https://api.github.com/repos/{GITHUB_REPO}'

def gh_get(path):
    r = requests.get(f'{GH_API}/{path}', headers=gh_hdrs())
    r.raise_for_status()
    return r.json()

def gh_put(path, data, sha=None):
    payload = {
        'message': 'Auto-update via photos_update.py',
        'content': base64.b64encode(json.dumps(data, indent=2).encode()).decode(),
        'branch': GITHUB_BRANCH
    }
    if sha: payload['sha'] = sha
    r = requests.put(f'{GH_API}/{path}', headers=gh_hdrs(), json=payload)
    r.raise_for_status()
    return r.json()

def get_config():
    try:
        info = gh_get('contents/config.json')
        c = json.loads(base64.b64decode(info['content']).decode())
        c['_sha'] = info['sha']
        return c
    except Exception as e:
        print(f'❌ Config fetch: {e}'); sys.exit(1)

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
        self.pw = None; self.browser = None; self.page = None

    def start(self):
        from playwright.sync_api import sync_playwright
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
        time.sleep(3)
        self.page.fill('input[placeholder="請輸入ID"]', MMS_EMAIL)
        self.page.fill('input[placeholder="請輸入密碼"]', MMS_PASSWORD)
        time.sleep(1)
        # Debug
        pw_test = self.page.evaluate("""()=>document.querySelector('form')?'form found':'no form'""")
        print(f'    Form check: {pw_test}')
        # Try React onFinish fiber (this worked in browser sessions)
        fiber_result = self.page.evaluate("""(args)=>{try{var f=document.querySelector('form');if(!f)return'no form';var k=Object.keys(f).find(k=>k.startsWith('__reactFiber')||k.startsWith('__reactInternalInstance'));if(!k)return'no react fiber';var x=f[k];while(x){var m=x.memoizedProps;if(m&&typeof m==='object'&&m.onFinish){m.onFinish({account:args.e,password:args.p});return'onFinish called';}x=x.return;}return'no onFinish';}catch(e){return'err:'+e.message;}}""", {'e': MMS_EMAIL, 'p': MMS_PASSWORD})
        print(f'    Fiber: {fiber_result}')
        if 'onFinish called' in str(fiber_result):
            print('    Waiting for login API response...')
            time.sleep(3)
            # Wait for redirect up to 15 seconds
            try:
                self.page.wait_for_url('**/product-management/**', timeout=15000)
                print('    Redirect detected!')
            except:
                print('    No redirect yet, checking page...')
                page_title = self.page.title()
                print(f'    Page title: {page_title}')
                page_url = self.page.url
                print(f'    URL: {page_url}')
                # Check for error messages
                err = self.page.evaluate("""()=>{var e=document.querySelector('.ant-message-error,.ant-alert-error,[class*=\"error\"]');return e?e.innerText:'no error';}""")
                print(f'    Error: {err}')
        else:
            print(f'    Trying requestSubmit...')
            sub2 = self.page.evaluate("""()=>{var f=document.querySelector('form');if(!f)return'no form';if(f.requestSubmit){f.requestSubmit();return'requestSubmit ok';}return'no requestSubmit';}""")
            print(f'    requestSubmit: {sub2}')
            time.sleep(5)
        current = self.page.url
        if 'login' in current.lower():
            # Take screenshot for debugging
            self.page.screenshot(path='/tmp/login_fail.png')
            raise Exception(f'Still on login page. URL: {current}')
        print('  ✅ Logged in')

    def update_photo(self, sku, photo_url, label=''):
        sku_id = sku.split('_S_')[-1] if '_S_' in sku else sku
        print(f'  📸 [{label}] {sku}...')
        try:
            self.page.goto('https://merchant.shoalter.com/product-management/product-list', wait_until='networkidle')
            time.sleep(2)
            inp = self.page.query_selector('input[placeholder="搜尋 SKU ID"]')
            if not inp: raise Exception('Search input not found')
            inp.fill(''); inp.fill(sku_id); time.sleep(0.5)
            sb = self.page.query_selector('button:has-text("搜 索")')
            if sb: sb.click()
            else:
                for b in self.page.query_selector_all('button'):
                    if '搜' in (b.inner_text() or ''): b.click(); break
            time.sleep(3)
            edit_url = self.page.evaluate("""(s)=>{var rows=document.querySelectorAll('tr.ant-table-row');for(var r of rows){var c=r.querySelectorAll('td');if(c.length>=4){var storeCell=c[2]?.innerText?.trim();if(storeCell===s){var links=c[c.length-1]?.querySelectorAll('a');if(links&&links.length>0)return links[links.length-1].href;}}}return null;}""", STORE_ID)
            if not edit_url: raise Exception(f'No row for store {STORE_ID}')
            self.page.goto(edit_url, wait_until='networkidle'); time.sleep(3)
            # Delete existing photos
            self.page.evaluate("""()=>{var d=document.querySelectorAll('[class*=\"ant-upload-list-item\"] [class*=\"delete\"],[aria-label=\"delete\"],.anticon-delete');for(var b of d){var btn=b.closest('button')||b.parentElement;if(btn)btn.click()}return true}""")
            time.sleep(1)
            result = self.page.evaluate("""async(u)=>{try{var r=await fetch(u);if(!r.ok)return'fetch fail:'+r.status;var b=await r.blob();var f=new File([b],'photo.jpg',{type:b.type||'image/jpeg'});var fi=document.querySelectorAll('input[type=\"file\"]');if(!fi||!fi[0])return'no input';var dt=new DataTransfer();dt.items.add(f);fi[0].files=dt.files;fi[0].dispatchEvent(new Event('change',{bubbles:true}));return'ok:'+f.size}catch(e){return'err:'+e.message}}""", photo_url)
            print(f'    Upload: {result}')
            if 'ok:' in result:
                time.sleep(2)
                done = self.page.evaluate("""()=>{var b=document.querySelectorAll('button');for(var x of b){if(x.innerText.trim()==='完 成'){x.click();return true;}}return false}""")
                print(f'    Done: {done}')
                time.sleep(3)
                return True
            return False
        except Exception as e:
            print(f'    ❌ {e}')
            return False

    def run(self, actions):
        if not actions: return []
        self.start()
        results = []
        try:
            self.login()
            for sku, url, lbl in actions:
                ok = self.update_photo(sku, url, lbl)
                results.append({'sku': sku, 'label': lbl, 'success': ok})
                time.sleep(2)
        finally:
            self.stop()
        return results

# ========== MAIN ==========
def main():
    print('🖼️ Bubble Photos v3 — Checking phases...')
    now = datetime.now()
    print(f'⏰ {now.isoformat()}')

    config = get_config()
    skus = config.get('skus', {})
    if not skus:
        print('✅ No SKUs'); return

    # Determine actions for each SKU
    actions = []
    status_changes = {}  # sku -> new_status

    for sku, entry in skus.items():
        status = entry.get('status', 'pending')
        phases = entry.get('phases', [])
        current_phase = entry.get('current_phase', -1)

        if status == 'completed':
            print(f'  ⏭️ {sku}: completed')
            continue

        # Find the next phase whose time has arrived
        next_phase = -1
        for i in range(current_phase + 1, len(phases)):
            p = phases[i]
            if not p.get('time'):
                print(f'  ⚠️ {sku}: phase {i} has no time, skipping')
                continue
            if not p.get('photo_url'):
                print(f'  ⚠️ {sku}: phase {i} has no photo_url, skipping')
                continue
            try:
                pt = datetime.fromisoformat(p['time'])
                if now >= pt:
                    next_phase = i
                    break  # Only process one phase per run
            except Exception as e:
                print(f'  ⚠️ {sku}: phase {i} bad time: {e}')

        if next_phase >= 0:
            p = phases[next_phase]
            print(f'  🟢 {sku}: Phase {next_phase+1} reached [{p.get("label","")}]')
            actions.append((sku, p['photo_url'], p.get('label', f'Phase {next_phase+1}')))
            status_changes[sku] = {'phase': next_phase, 'label': p.get('label', '')}
        else:
            # Show time to next phase
            for i in range(current_phase + 1, len(phases)):
                p = phases[i]
                if p.get('time'):
                    try:
                        pt = datetime.fromisoformat(p['time'])
                        if pt > now:
                            mins = int((pt - now).total_seconds() / 60)
                            print(f'  ⏳ {sku}: Phase {i+1} in {mins} min [{p.get("label","")}]')
                            break
                    except: pass

    if not actions:
        print('✅ No actions needed')
        return

    print(f'\n📦 {len(actions)} phase(s) to process')
    updater = MMSUpdater()
    results = updater.run(actions)

    # Update config
    for r in results:
        sku = r['sku']
        ok = r['success']
        ch = status_changes.get(sku, {})

        if sku in skus:
            if ok:
                new_phase = ch.get('phase', -1)
                skus[sku]['current_phase'] = new_phase
                skus[sku]['last_updated'] = now.isoformat()
                # Check if all phases done
                if new_phase >= len(skus[sku].get('phases', [])) - 1:
                    skus[sku]['status'] = 'completed'
                else:
                    skus[sku]['status'] = 'active'
            else:
                skus[sku]['status'] = 'failed'

    # Save log
    dashboard = get_dashboard_data()
    if 'history' not in dashboard: dashboard['history'] = []
    for r in results:
        dashboard['history'].append({
            'sku': r['sku'],
            'label': r.get('label', ''),
            'photo': '',
            'status': 'success' if r['success'] else 'failed',
            'time': now.isoformat()
        })
    dashboard['history'] = dashboard['history'][-500:]

    config.pop('_sha', None)
    save_json('config.json', config)
    save_json('dashboard_data.json', dashboard)
    print('✅ All saved!')

if __name__ == '__main__':
    main()
