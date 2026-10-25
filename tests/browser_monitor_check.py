"""CPU fixture browser check for monitor freshness, reflow and JSON export."""
from pathlib import Path
import json
import subprocess
import time
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'build' / 'monitor'
OUT.mkdir(parents=True, exist_ok=True)
server = subprocess.Popen(['node', 'tests/local_server.mjs'], cwd=ROOT,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    for _ in range(100):
        if server.poll() is not None:
            raise RuntimeError(server.stderr.read().decode())
        try:
            urlopen('http://127.0.0.1:8765', timeout=1).close()
            break
        except OSError:
            time.sleep(.1)
    else:
        raise RuntimeError('Fixture did not start')
    with sync_playwright() as p:
        browser = p.chromium.launch(args=['--no-sandbox'])
        page = browser.new_page(viewport={'width':1440, 'height':1100})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        sample_at = time.time() - 30
        def state(route):
            data = route.fetch().json()
            data['heartbeat']['resources'] = [dict(id='fixture-instance', status='online', telemetry=dict(
                at=sample_at, host='fixture-gpu-host', gpus=[dict(index=0, name='H100',
                used_mb=40960, total_mb=81920, utilization=65, temperature_c=61)]))]
            route.fulfill(json=data)
        page.route('**/api/state', state)
        page.route('**/api/host', lambda route: route.fulfill(json={'available':True,'at':time.time(),'text':'42 个线程\n8 个进程 · fixture-user'}))
        page.goto('http://127.0.0.1:8765')
        expect(page.locator('#account-summary')).to_contain_text('42 个线程')
        page.locator('.account-monitor summary').click()
        expect(page.locator('#account-threads')).to_contain_text('fixture-user')
        expect(page.locator('#server-resources')).to_contain_text('61 °C')
        expect(page.locator('#server-resources')).to_contain_text('40.0 / 80.0 GiB')
        expect(page.locator('#memory-value')).to_contain_text('GiB')
        sample_at += 25
        page.locator('#refresh').click()
        expect(page.locator('.monitor-trend svg')).to_be_visible()
        for width in [1440, 800, 390, 320]:
            page.set_viewport_size({'width':width, 'height':1100})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
            if width in [1440, 390]:
                page.screenshot(path=str(OUT / f'monitor-{width}.png'), full_page=True)
        with page.expect_download() as download:
            page.locator('#export-monitor').click()
        download.value.save_as(OUT / 'fixture-monitor.json')
        exported = json.loads((OUT / 'fixture-monitor.json').read_text())
        assert len(exported['resources'][0]['history']) == 2
        sample_at = time.time() - 100
        page.locator('#refresh').click()
        expect(page.locator('.monitor-status')).to_contain_text('采样过期')
        expect(page.locator('#server-resources')).not_to_contain_text('61 °C')
        page.unroute('**/api/state')
        page.route('**/api/state', lambda route: route.abort())
        page.locator('#refresh').click()
        expect(page.locator('#account-summary')).to_contain_text('非实时')
        assert not errors, errors
        browser.close()
        print('Monitor browser checks passed: metrics, trend, JSON export, stale sample, 320–1440px reflow.')
finally:
    server.terminate()
    server.communicate(timeout=10)
