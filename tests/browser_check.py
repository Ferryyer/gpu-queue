from playwright.sync_api import sync_playwright,expect
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parent.parent
ids={n:'GQ-'+str(n).zfill(16) for n in range(1,5)}
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,args=['--no-sandbox','--renderer-process-limit=1','--disable-gpu','--disable-dev-shm-usage','--no-zygote','--single-process','--num-raster-threads=1','--js-flags=--single-threaded','--disable-software-rasterizer'])
 errors=[]
 context=browser.new_context(viewport={'width':1440,'height':1100})
 page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
 page.goto('http://127.0.0.1:8765/',wait_until='networkidle')
 expect(page.locator('.task-row')).to_have_count(4)
 page.locator(f'[data-id="{ids[3]}"] .grip').drag_to(page.locator(f'[data-id="{ids[2]}"]'))
 expect(page.locator(f'[data-id="{ids[3]}"] .queue-position')).to_have_text('队列第 1 位')
 page.locator(f'[data-id="{ids[4]}"] .task-title').click()
 page.locator('[data-detail-start]').click()
 expect(page.locator(f'[data-id="{ids[4]}"] .queue-position')).to_have_text('队列第 3 位')
 page.reload(wait_until='networkidle')
 expect(page.locator(f'[data-id="{ids[3]}"] .queue-position')).to_have_text('队列第 1 位')
 page.locator(f'[data-id="{ids[1]}"] .task-title').click();page.locator('[data-step="0"]').click()
 expect(page.locator('.log-box')).to_contain_text('GPU test log')
 page.request.post('http://127.0.0.1:8765/test/fail');page.locator('#refresh').click()
 expect(page.locator('.pipeline-step.failed')).to_have_count(1);expect(page.locator('.pipeline-step.skipped')).to_have_count(1)
 page.locator('#integration').click();expect(page.locator('#integration-dialog')).to_be_visible();page.locator('#close-dialog-bottom').click()
 expect(page.locator('#demo,#fail-demo,#reset')).to_have_count(0)
 assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
 (ROOT/'desktop-preview.png').write_bytes(page.screenshot(full_page=True))
 browser.close()
 browser=p.chromium.launch(headless=True,args=['--no-sandbox','--renderer-process-limit=1','--disable-gpu','--disable-dev-shm-usage','--no-zygote','--single-process','--num-raster-threads=1','--js-flags=--single-threaded','--disable-software-rasterizer'])
 mobile=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
 mp=mobile.new_page();mp.on('pageerror',lambda error:errors.append(str(error)))
 mp.goto('http://127.0.0.1:8765/',wait_until='networkidle');expect(mp.locator('.task-row')).to_have_count(4)
 assert mp.evaluate('document.documentElement.scrollWidth <= innerWidth')
 mp.locator(f'[data-id="{ids[2]}"] .grip').scroll_into_view_if_needed()
 source=mp.locator(f'[data-id="{ids[2]}"] .grip').bounding_box();target=mp.locator(f'[data-id="{ids[3]}"]').bounding_box()
 x=source['x']+source['width']/2;start_y=source['y']+source['height']/2;end_y=target['y']+target['height']/2
 cdp=mobile.new_cdp_session(mp);cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':x,'y':start_y}]})
 for i in range(1,9):
  cdp.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':x,'y':start_y+(end_y-start_y)*i/8}]});mp.wait_for_timeout(20)
 cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
 expect(mp.locator(f'[data-id="{ids[2]}"] .queue-position')).to_have_text('队列第 1 位')
 mp.locator(f'[data-id="{ids[1]}"] .task-title').click();expect(mp.locator('#detail h2')).to_contain_text('真实链路测试')
 (ROOT/'mobile-preview.png').write_bytes(mp.screenshot(full_page=True))
 assert not errors,errors
 print(json.dumps({'checks':['server-backed task list','browser-only start','persistent order','desktop drag','touch drag','real step log rendering','failure stops later steps','desktop/mobile layouts'],'page_errors':errors},ensure_ascii=False))
 browser.close()
