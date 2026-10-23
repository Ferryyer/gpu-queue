from playwright.sync_api import sync_playwright,expect
import json
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=['--no-sandbox','--renderer-process-limit=1','--disable-gpu','--disable-dev-shm-usage','--no-zygote','--single-process','--num-raster-threads=1','--js-flags=--single-threaded','--disable-software-rasterizer'])
    page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://127.0.0.1:8765/',wait_until='networkidle')
    task='GQ-'+str(1).zfill(16)
    page.locator(f'[data-id="{task}"] .task-title').click()
    page.locator('[data-detail-stop]').click();expect(page.locator('#stop-dialog')).to_be_visible()
    page.locator('#cancel-stop').click();expect(page.locator('#stop-dialog')).not_to_be_visible()
    expect(page.locator('[data-detail-stop]')).to_be_visible()
    page.locator('[data-detail-stop]').click();page.locator('#confirm-stop').click()
    expect(page.locator('#detail .badge')).to_have_text('正在停止')
    page.reload(wait_until='networkidle');expect(page.locator('#detail .badge')).to_have_text('正在停止')
    page.request.post('http://127.0.0.1:8765/test/stop-confirm');page.locator('#refresh').click()
    expect(page.locator('#detail .badge')).to_have_text('已停止')
    expect(page.locator('.pipeline-step.stopped')).to_have_count(1)
    expect(page.locator('.pipeline-step.skipped')).to_have_count(2)
    page.locator('[data-step="0"]').click();expect(page.locator('.log-box')).to_contain_text('GPU test log')
    queued='GQ-'+str(2).zfill(16)
    page.locator(f'[data-id="{queued}"] .task-title').click();page.locator('[data-detail-stop]').click();page.locator('#confirm-stop').click()
    expect(page.locator('#detail .badge')).to_have_text('已取消')
    expect(page.locator(f'[data-id="{queued}"] .grip')).to_have_count(0)
    page.reload(wait_until='networkidle')
    expect(page.locator(f'[data-id="{queued}"] .badge')).to_have_text('已取消')
    assert not errors,errors
    print(json.dumps({'checks':['stop confirmation and dismissal','running task stays stopping before proof','proof changes state to stopped','logs retained','later steps skipped','queued task removed','reload preserves cancellations'],'page_errors':errors},ensure_ascii=False))
    browser.close()
