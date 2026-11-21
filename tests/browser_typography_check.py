"""CPU-only browser audit with isolated fixture data; never connects to a GPU service.
Run after `node scripts/build.mjs`, with Playwright + Chromium installed.
"""
from pathlib import Path
import json
import subprocess
import time
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / 'build' / 'typography'
ARTIFACTS.mkdir(parents=True, exist_ok=True)
BASE = 'http://127.0.0.1:8765'
AUDIT = r'''() => {
 const rgb = c => (c.match(/[\d.]+/g)||[]).map(Number);
 const blend = (a,b) => a.slice(0,3).map((v,i)=>v*(a[3]??1)+b[i]*(1-(a[3]??1)));
 const lum = c => c.map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
 let failures=[], min=100, count=0;
 for(const el of document.querySelectorAll('body *')){
  if(![...el.childNodes].some(n=>n.nodeType===3 && /[\p{L}\p{N}]/u.test(n.textContent)))continue;
  const cs=getComputedStyle(el), rect=el.getBoundingClientRect();
  if(!rect.width||!rect.height||cs.visibility==='hidden'||el.closest('[hidden]'))continue;
  let chain=[], p=el;while(p){chain.unshift(p);p=p.parentElement;}
  let bg=[255,255,255];for(const p of chain)bg=blend(rgb(getComputedStyle(p).backgroundColor),bg);
  let fg=blend(rgb(cs.color),bg), a=lum(fg), b=lum(bg), ratio=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
  const size=parseFloat(cs.fontSize), large=size>=24||(size>=18.66&&Number(cs.fontWeight)>=700);
  if(size===0 && el.hasAttribute('aria-label'))continue;
  count++;min=Math.min(min,ratio);
  if(ratio<(large?3:4.5)||size<12)failures.push({tag:el.tagName,cls:el.className,text:el.textContent.trim().slice(0,55),size,ratio:Math.round(ratio*100)/100});
 }
 return {count,minContrast:Math.round(min*100)/100,failures,overflow:document.documentElement.scrollWidth>innerWidth};
}'''
server = subprocess.Popen(['node','tests/local_server.mjs'], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
 for _ in range(100):
  if server.poll() is not None: raise RuntimeError(server.stderr.read().decode())
  try:
   urlopen(BASE,timeout=1).close();break
  except OSError: time.sleep(.1)
 else: raise RuntimeError('Fixture server did not become ready')
 with sync_playwright() as p:
  browser=p.chromium.launch(args=['--no-sandbox'])
  page=browser.new_page(viewport={'width':1440,'height':1100})
  errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(BASE,wait_until='networkidle');expect(page.locator('.task-row')).to_have_count(4)
  # The committed predecessor provides a reproducible before image.
  original=subprocess.check_output(['git','show','16177c7:web/style.css'],cwd=ROOT).decode()
  page.route('**/style.css',lambda route:route.fulfill(body=original,content_type='text/css'))
  page.reload(wait_until='networkidle')
  baseline=page.evaluate(AUDIT)
  page.screenshot(path=str(ARTIFACTS/'desktop-before.png'),full_page=True)
  page.unroute('**/style.css');page.reload(wait_until='networkidle')
  results=[]
  for width in [1440,1280,1024,800,640,390,320]:
   page.set_viewport_size({'width':width,'height':1100 if width>600 else 844})
   # Exercise long Chinese/Latin text without changing the fixture's task state.
   page.locator('.task-title').first.evaluate("e=>e.textContent='中文长任务标题与 English experiment / '+ 'very-long-project-name-'.repeat(5)")
   page.locator('#detail h2').evaluate("e=>e.textContent='长任务详情标题：训练、评测与推理 / '+ 'longversion'.repeat(8)")
   result=page.evaluate(AUDIT);result['width']=width;results.append(result)
   assert not result['overflow'],result
   assert not result['failures'],result
   if width in (1440,390):page.screenshot(path=str(ARTIFACTS/('desktop-long-title.png' if width==1440 else 'mobile-long-title.png')),full_page=True)
  # 200% layout zoom at a 1280px display corresponds to a 640px CSS viewport.
  page.set_viewport_size({'width':640,'height':550})
  page.locator('#interaction-mode').click();expect(page.locator('#interaction-mode')).to_have_attribute('aria-pressed','true')
  page.keyboard.press('Shift+Tab');expect(page.locator('#interaction-mode')).to_have_attribute('aria-pressed','false')
  page.locator('#search-toggle').click();page.locator('#search').fill('no-such-task');expect(page.locator('#task-list .empty')).to_be_visible()
  page.locator('#search').fill('');page.locator('#search').focus();page.keyboard.press('Shift+Tab')
  expect(page.locator('#interaction-mode')).to_have_attribute('aria-pressed','false')
  page.set_viewport_size({'width':1440,'height':1100})
  page.locator('#integration').click();expect(page.locator('#integration-dialog')).to_be_visible()
  audit=page.evaluate(AUDIT);assert not audit['failures'],audit
  page.keyboard.press('Escape');expect(page.locator('#integration-dialog')).not_to_be_visible()
  page.set_viewport_size({'width':390,'height':844});page.emulate_media(color_scheme='dark',reduced_motion='reduce')
  audit=page.evaluate(AUDIT);assert not audit['failures'],audit
  page.emulate_media(color_scheme='light',reduced_motion='no-preference')
  for width,filename in [(1440,'desktop-after.png'),(390,'mobile-after.png')]:
   page.set_viewport_size({'width':width,'height':1100 if width>600 else 844})
   page.reload(wait_until='networkidle')
   page.screenshot(path=str(ARTIFACTS/filename),full_page=True)
  page.locator('[data-id="GQ-0000000000000001"] .task-title').click()
  page.locator('[data-detail-stop]').click();expect(page.locator('#stop-dialog')).to_be_visible()
  audit=page.evaluate(AUDIT);assert not audit['failures'],audit
  page.locator('#cancel-stop').click()
  page.locator('#back-to-tasks').click()
  page.request.post(BASE+'/test/fail');page.locator('#refresh').click()
  page.locator('[data-id="GQ-0000000000000001"] .task-title').click()
  expect(page.locator('.pipeline-step.failed')).to_have_count(1)
  audit=page.evaluate(AUDIT);assert not audit['failures'],audit
  page.locator('[data-step="1"]').click();expect(page.locator('.log-box')).to_contain_text('evaluation failed')
  audit=page.evaluate(AUDIT);assert not audit['failures'],audit
  assert not errors,errors
  browser.close()
 report={'fixture':'CPU only, 4 synthetic tasks','baseline':baseline,'viewports':results,'interactionChecks':['Edit/Auto and Shift+Tab','input focus navigation','search empty state','dialog open / Escape','dark OS preference','reduced motion'],'pageErrors':errors}
 (ARTIFACTS/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(report,ensure_ascii=False))
finally:
 server.terminate()
 server.communicate(timeout=10)
