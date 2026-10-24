"""CPU fixtures: focus survives polling; failure never advertises live GPU; mobile detail."""
from pathlib import Path
import json, subprocess, time
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'build/unified'
OUT.mkdir(parents=True, exist_ok=True)
server = subprocess.Popen(['node', 'tests/local_server.mjs'], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    for _ in range(100):
        if server.poll() is not None: raise RuntimeError(server.stderr.read().decode())
        try: urlopen('http://127.0.0.1:8765', timeout=1).close(); break
        except OSError: time.sleep(.1)
    else: raise RuntimeError('Fixture failed to start')
    with sync_playwright() as p:
        browser = p.chromium.launch(args=['--no-sandbox'])
        page = browser.new_page(viewport={'width':1440,'height':1000})
        errors=[]; page.on('pageerror', lambda e: errors.append(str(e)))
        sampled=time.time()-35
        def state(route):
            data=route.fetch().json()
            data['heartbeat']['resources']=[dict(id='fixture-gpu',status='online',telemetry=dict(at=sampled,host='fixture-host',gpus=[dict(index=0,name='H100',used_mb=40960,total_mb=81920,utilization=65,temperature_c=61)]))]
            route.fulfill(json=data)
        page.route('**/api/state',state)
        page.route('**/api/host',lambda r:r.fulfill(json={'available':True,'at':time.time(),'text':'42 个线程\n8 个进程 · fixture'}))
        page.goto('http://127.0.0.1:8765',wait_until='networkidle')
        expect(page.locator('.task-row')).to_have_count(4)
        button=page.locator('[data-move="down"]:not([disabled])').first
        button.focus(); before=button.evaluate('(el)=>el.closest("[data-id]").dataset.id')
        page.wait_for_timeout(10500)
        assert page.evaluate('document.activeElement.dataset.move')=='down'
        assert page.evaluate('document.activeElement.closest("[data-id]").dataset.id')==before
        # Keyboard still acts on that task after both polling cycles.
        page.keyboard.press('Enter')
        expect(page.locator(f'[data-id="{before}"] .queue-position')).to_have_text('队列第 2 位')
        page.locator('.full-monitor>summary').click()
        page.locator('#refresh').click()
        expect(page.locator('#server-resources')).to_contain_text('61 °C')
        sampled+=25; page.locator('#refresh').click()
        expect(page.locator('.monitor-trend circle')).to_have_count(2)
        expect(page.locator('.monitor-trend')).to_contain_text('已累计 25 秒')
        expect(page.locator('.monitor-trend')).to_contain_text('真实时间比例')
        page.screenshot(path=str(OUT/'desktop-1440.png'),full_page=True)
        page.unroute('**/api/state');page.route('**/api/state',lambda r:r.abort())
        page.locator('#refresh').click()
        expect(page.locator('.prototype-tag')).to_have_text('连接异常')
        expect(page.locator('.monitor-status')).to_contain_text('非实时')
        expect(page.locator('.monitor-status.fresh')).to_have_count(0)
        expect(page.locator('#server-resources')).not_to_contain_text('61 °C')
        expect(page.locator('#gpu-value')).to_have_text('—')
        page.screenshot(path=str(OUT/'disconnected.png'),full_page=True)
        page.unroute('**/api/state');page.route('**/api/state',state)
        page.locator('#refresh').click();expect(page.locator('.monitor-status.fresh')).to_have_count(1)
        page.locator('.full-monitor>summary').click()
        for width in [320,390,640,800,1024,1440]:
            page.set_viewport_size({'width':width,'height':844})
            page.evaluate('scrollTo(0,0)')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            if width==390:
                assert page.locator('.task-row').first.bounding_box()['y']<844
                page.screenshot(path=str(OUT/'mobile-390.png'),full_page=True)
                page.locator('.task-row .task-title').first.click()
                expect(page.locator('#back-to-tasks')).to_be_visible()
                assert page.locator('#back-to-tasks').bounding_box()['y']<100
                page.screenshot(path=str(OUT/'mobile-detail.png'))
                page.locator('#back-to-tasks').click()
                expect(page.locator('.task-row').first).to_be_visible()
        # Explicit actions only: toggling modes, failed reads and recovery do
        # not authorize any ready fixture task.
        assert next(t for t in page.request.get('http://127.0.0.1:8765/api/state').json()['tasks'] if t['id']=='GQ-0000000000000004')['approved_at'] is None
        assert not errors,errors
        browser.close()
        (OUT/'checks.json').write_text(json.dumps({'focusPolls':2,'keyboardActionAfterPoll':True,'widths':[320,390,640,800,1024,1440],'freshnessFailureRecovery':True,'mobileDetail':True,'errors':errors},indent=2))
        print('Unified web checks passed: two polls + Enter, disconnected/recovered metrics, responsive task-first layout, mobile detail.')
finally:
    server.terminate();server.communicate(timeout=10)
