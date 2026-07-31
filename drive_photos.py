#!/usr/bin/env python3
"""
Fetch public Google Drive folder file list and push to GitHub as drive_photos.json.
Frontend reads this JSON (raw.githubusercontent, CORS-friendly) instead of hitting
Google Drive directly (which is CORS-blocked in browsers).
"""
import os, json, base64, re, requests

GITHUB_REPO = 'FIFICHECK/bubble-photos-dashboard'
GITHUB_BRANCH = 'master'
DRIVE_FOLDER = '1xyzWMrEK7EMsVKBBH2_8dRMYVCXK0E5q'

def get_token():
    t = os.environ.get('BUBBLE_PHOTOS_TOKEN', '')
    if not t:
        with open(os.path.expanduser('~/.config/gh/hosts.yml')) as f:
            for line in f:
                if 'oauth_token' in line:
                    t = line.split(':')[1].strip()
    return t

def main():
    tok = get_token()
    h = {'Authorization': f'token {tok}', 'Accept': 'application/vnd.github.v3+json'}

    # Fetch embedded folder view (public folders only)
    url = f'https://drive.google.com/embeddedfolderview?id={DRIVE_FOLDER}#list'
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    html = r.text

    # Parse entries: flip-entry div with id="entry-{FILE_ID}" + flip-entry-title
    entries = []
    re_entry = re.compile(
        r'<div class="flip-entry"[^>]*id="entry-([^"]+)"[\s\S]*?flip-entry-title">([\s\S]*?)</div>'
    )
    for m in re_entry.finditer(html):
        fid = m.group(1).strip()
        name = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        if fid:
            entries.append({'name': name, 'link': f'https://drive.google.com/file/d/{fid}/view'})

    # Fallback: data-id attributes
    if not entries:
        for m in re.finditer(r'data-id="([^"]+)"', html):
            entries.append({'name': '', 'link': f'https://drive.google.com/file/d/{m.group(1)}/view'})

    if not entries:
        print(f'❌ No entries found (html size {len(html)})')
        return

    # Convert links to file IDs (canonical form)
    files = []
    for e in entries:
        fid = e['link'].split('/file/d/')[1] if '/file/d/' in e['link'] else ''
        fid = fid.split('/')[0]
        if fid:
            files.append({'name': e['name'], 'file_id': fid})

    data = {'folder_id': DRIVE_FOLDER, 'updated': __import__('datetime').datetime.now().isoformat(), 'files': files}

    # Push to GitHub
    api = f'https://api.github.com/repos/{GITHUB_REPO}/contents/drive_photos.json?ref={GITHUB_BRANCH}'
    try:
        info = requests.get(api, headers=h).json()
        sha = info.get('sha')
    except Exception:
        sha = None

    payload = {
        'message': 'Auto-update drive_photos.json',
        'content': base64.b64encode(json.dumps(data, indent=2, ensure_ascii=False).encode()).decode(),
        'branch': GITHUB_BRANCH
    }
    if sha:
        payload['sha'] = sha
    r2 = requests.put(api, headers=h, json=payload)
    r2.raise_for_status()
    print(f'✅ drive_photos.json updated: {len(files)} files')

if __name__ == '__main__':
    main()
