#!/usr/bin/env python3
"""
Bubble Photos Update — MMS Product Photo Auto-Updater
Reads config.json from GitHub, logs into MMS 2.0, and updates main product photos.
"""
import os, sys, json, base64, time, re, requests
from datetime import datetime
from playwright.sync_api import sync_playwright

# ======================== CONFIG ========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GITHUB_REPO = 'FIFICHECK/bubble-photos-dashboard'
GITHUB_BRANCH = 'master'
GITHUB_TOKEN = os.environ.get('BUBBLE_PHOTOS_TOKEN', '')
MMS_EMAIL = '***REDACTED***'
MMS_PASSWORD = '***REDACTED***!!!'
STORE_ID = 'B0961005'

# ======================== GITHUB HELPERS ========================
GH_HEADERS = {
    'Authorization': f'token {GITHUB_TOKEN}',
    'Accept': 'application/vnd.github.v3+json'
}
GH_API = f'https://api.github.com/repos/{GITHUB_REPO}'

def gh_get(path):
    r = requests.get(f'{GH_API}/{path}', headers=GH_HEADERS)
    r.raise_for_status()
    return r.json()

def gh_put(path, data, sha=None):
    payload = {
        'message': 'Auto-update via photos_update.py',
        'content': base64.b64encode(json.dumps(data, indent=2).encode()).decode(),
        'branch': GITHUB_BRANCH
    }
    if sha:
        payload['sha'] = sha
    r = requests.put(f'{GH_API}/{path}', headers=GH_HEADERS, json=payload)
    r.raise_for_status()
    return r.json()

def get_config():
    info = gh_get('contents/config.json')
    config = json.loads(base64.b64decode(info['content']).decode())
    config['_sha'] = info['sha']
    return config

def get_dashboard_data():
    try:
        info = gh_get('contents/dashboard_data.json')
        data = json.loads(base64.b64decode(info['content']).decode())
        data['_sha'] = info['sha']
        return data
    except:
        return {'all_skus': [], 'updated_skus': [], 'failed_skus': [], 'pending_skus': [], 'history': [], 'last_checked': '', 'total_updates': 0, 'successful_updates': 0, 'failed_updates': 0, '_sha': None}

def save_dashboard_data(data):
    sha = data.pop('_sha', None)
    result = gh_put('contents/dashboard_data.json', data, sha)
    return result

# ======================== MMS BROWSER AUTOMATION ========================
class MMSPhotoUpdater:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.page = None
        self.results = []

    def start_browser(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=True)
        self.page = self.browser.new_page()
        self.page.set_viewport_size({'width': 1920, 'height': 1080})

    def close_browser(self):
        try:
            if self.browser:
                self.browser.close()
        except: pass
        try:
            if self.playwright:
                self.playwright.stop()
        except: pass

    def login(self):
        """Login to MMS 2.0 using React onFinish fiber technique"""
        print('  🔑 Logging into MMS...')
        self.page.goto('https://merchant.shoalter.com/login', wait_until='networkidle')
        time.sleep(2)

        # Fill credentials
        self.page.fill('input[placeholder="請輸入ID"]', MMS_EMAIL)
        self.page.fill('input[placeholder="請輸入密碼"]', MMS_PASSWORD)

        # Use React onFinish fiber to bypass bot detection
        result = self.page.evaluate("""
            () => {
                var formEl = document.querySelector('form');
                if (!formEl) return 'no form';
                var fiberKey = Object.keys(formEl).find(k => k.startsWith('__reactFiber'));
                if (!fiberKey) return 'no fiber';
                var fiber = formEl[fiberKey];
                var loggedIn = false;
                while (fiber && !loggedIn) {
                    var p = fiber.memoizedProps;
                    if (p && typeof p === 'object' && p.onFinish) {
                        p.onFinish({
                            account: arguments[0],
                            password: arguments[1]
                        });
                        loggedIn = true;
                    }
                    fiber = fiber.return;
                }
                return loggedIn ? 'ok' : 'not found';
            }
        """, MMS_EMAIL, MMS_PASSWORD)

        if result != 'ok':
            raise Exception(f'Login failed: {result}')

        time.sleep(3)
        # Verify login success
        current_url = self.page.url
        if 'login' in current_url.lower():
            raise Exception('Login failed - still on login page')

        print('  ✅ Login successful')

    def update_sku_photo(self, sku, photo_url):
        """Update the main photo for a single SKU"""
        print(f'  📸 Updating {sku}...')
        sku_id = sku.split('_S_')[-1] if '_S_' in sku else sku

        try:
            # Navigate to product list
            self.page.goto('https://merchant.shoalter.com/product-management/product-list', wait_until='networkidle')
            time.sleep(2)

            # Search for SKU
            search_input = self.page.query_selector('input[placeholder="搜尋 SKU ID"]')
            if not search_input:
                raise Exception('Search input not found')
            search_input.fill('')
            search_input.fill(sku_id)
            time.sleep(0.5)

            # Click search button
            search_btn = self.page.query_selector('button:has-text("搜 索")')
            if not search_btn:
                search_btn = self.page.query_selector('button:has-text("搜尋")')
            if search_btn:
                search_btn.click()
            else:
                # Fallback: try all buttons
                buttons = self.page.query_selector_all('button')
                for btn in buttons:
                    if '搜' in (btn.inner_text() or ''):
                        btn.click()
                        break
            time.sleep(3)

            # Get the edit URL for our store
            edit_url = self.page.evaluate("""
                (targetStore) => {
                    var rows = document.querySelectorAll('tr.ant-table-row');
                    for (var row of rows) {
                        var cells = row.querySelectorAll('td');
                        if (cells.length >= 4) {
                            var storeId = cells[3]?.innerText?.trim();
                            if (storeId === targetStore) {
                                var lastCell = cells[cells.length - 1];
                                var link = lastCell?.querySelector('a');
                                if (link) return link.href;
                            }
                        }
                    }
                    return null;
                }
            """, STORE_ID)

            if not edit_url:
                raise Exception(f'No matching row found for store {STORE_ID}')

            # Navigate to edit page
            self.page.goto(edit_url, wait_until='networkidle')
            time.sleep(3)

            # Delete existing main photo
            deleted = self.page.evaluate("""
                () => {
                    var deleteBtns = document.querySelectorAll('[class*="ant-upload-list-item"] [class*="delete"], [aria-label="delete"]');
                    for (var btn of deleteBtns) {
                        btn.click();
                        return true;
                    }
                    // Try finding delete by icon
                    var icons = document.querySelectorAll('.anticon-delete');
                    for (var icon of icons) {
                        var btn = icon.closest('button') || icon.parentElement;
                        if (btn) { btn.click(); return true; }
                    }
                    return false;
                }
            """)
            print(f'    🗑️ Photo deleted: {deleted}')
            time.sleep(1)

            # Fetch photo from URL and upload
            upload_result = self.page.evaluate("""
                async (url) => {
                    try {
                        var resp = await fetch(url);
                        if (!resp.ok) return 'fetch failed: HTTP ' + resp.status;
                        var blob = await resp.blob();
                        var file = new File([blob], 'product_photo.jpg', { type: blob.type || 'image/jpeg' });
                        var fileInputs = document.querySelectorAll('input[type="file"]');
                        if (!fileInputs || fileInputs.length === 0) return 'no file input';
                        var target = fileInputs[0];
                        var dt = new DataTransfer();
                        dt.items.add(file);
                        target.files = dt.files;
                        target.dispatchEvent(new Event('change', { bubbles: true }));
                        return 'uploaded:' + file.size;
                    } catch(e) {
                        return 'error:' + e.message;
                    }
                }
            """, photo_url)
            print(f'    📤 Upload result: {upload_result}')

            if upload_result and upload_result.startswith('uploaded:'):
                time.sleep(2)

                # Click "完成" (Done) button
                done_clicked = self.page.evaluate("""
                    () => {
                        var allBtns = document.querySelectorAll('button');
                        for (var btn of allBtns) {
                            if (btn.innerText.trim() === '完 成') {
                                btn.click();
                                return true;
                            }
                        }
                        return false;
                    }
                """)
                print(f'    ✅ Done button clicked: {done_clicked}')
                time.sleep(3)

                return {'sku': sku, 'status': 'success', 'message': 'Photo updated successfully'}
            else:
                return {'sku': sku, 'status': 'failed', 'message': str(upload_result)}

        except Exception as e:
            print(f'    ❌ Error: {e}')
            return {'sku': sku, 'status': 'failed', 'message': str(e)}

    def run(self, skus_to_update):
        """Run updates for a list of SKUs"""
        self.start_browser()
        try:
            self.login()
            for sku, photo_url in skus_to_update:
                result = self.update_sku_photo(sku, photo_url)
                self.results.append(result)
                time.sleep(2)
        finally:
            self.close_browser()
        return self.results

# ======================== MAIN ========================
def main():
    print('🖼️ Bubble Photos Update — Starting...')
    print(f'⏰ {datetime.now().isoformat()}')

    # Load config
    print('📥 Loading config from GitHub...')
    config = get_config()
    skus = config.get('skus', [])
    photo_urls = config.get('sku_photo_urls', {})

    # Find SKUs that need updating (have photo URLs)
    to_update = []
    for sku in skus:
        url = photo_urls.get(sku, '')
        if url:
            to_update.append((sku, url))

    if not to_update:
        print('✅ No SKUs with photo URLs to update')
        return

    print(f'📦 Found {len(to_update)} SKUs to update')

    # Load existing dashboard data
    dashboard = get_dashboard_data()
    if 'all_skus' not in dashboard:
        dashboard['all_skus'] = []
    if 'updated_skus' not in dashboard:
        dashboard['updated_skus'] = []
    if 'failed_skus' not in dashboard:
        dashboard['failed_skus'] = []
    if 'pending_skus' not in dashboard:
        dashboard['pending_skus'] = []
    if 'history' not in dashboard:
        dashboard['history'] = []
    dashboard['last_checked'] = datetime.now().isoformat()

    # Run updates
    updater = MMSPhotoUpdater()
    results = updater.run(to_update)

    # Process results
    for result in results:
        sku = result['sku']
        status = result['status']
        message = result.get('message', '')
        product_name = result.get('product_name', '')

        # Add to history
        dashboard['history'].append({
            'sku': sku,
            'status': status,
            'message': message,
            'product_name': product_name,
            'checked_at': datetime.now().isoformat()
        })

        if status == 'success':
            dashboard['updated_skus'] = [u for u in dashboard.get('updated_skus', []) if u.get('sku') != sku]
            dashboard['updated_skus'].append({
                'sku': sku,
                'product_name': product_name,
                'updated_at': datetime.now().isoformat()
            })
            dashboard['successful_updates'] = dashboard.get('successful_updates', 0) + 1
        else:
            dashboard['failed_skus'] = [u for u in dashboard.get('failed_skus', []) if u.get('sku') != sku]
            dashboard['failed_skus'].append({
                'sku': sku,
                'product_name': product_name,
                'message': message,
                'checked_at': datetime.now().isoformat()
            })
            dashboard['failed_updates'] = dashboard.get('failed_updates', 0) + 1

        # Update all_skus
        dashboard['all_skus'] = [a for a in dashboard.get('all_skus', []) if a.get('sku') != sku]
        dashboard['all_skus'].append({
            'sku': sku,
            'product_name': product_name,
            'photo_url': photo_urls.get(sku, ''),
            'status': status,
            'last_checked': datetime.now().isoformat()
        })

    # Trim history to last 500 entries
    dashboard['history'] = dashboard['history'][-500:]
    dashboard['total_updates'] = dashboard.get('total_updates', 0) + len(results)

    # Save dashboard data
    print('📤 Saving results to GitHub...')
    save_dashboard_data(dashboard)
    print('✅ Done!')

if __name__ == '__main__':
    main()
