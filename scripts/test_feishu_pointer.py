#!/usr/bin/env python3
"""Exercise the production userscript with synthetic task controls in Chromium.

Requires Playwright and its Chromium binary. All requests are intercepted; no
tenant data or authentication is used. CSS zoom and device pixel ratios cover
DOM hit testing, not Flutter/AppKit event delivery or a signed-in Feishu page.
"""
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = (ROOT / 'serverbox/assets/feishu/inspire-task.user.js').read_text()
URL = 'https://uqyv5nolng8.feishu.cn/next/task/my-tasks'
FIXTURE = '''<!doctype html><meta charset="utf-8"><style>
body { margin: 0; }
.layout { display: flex; min-height: 400px; }
aside { flex: 0 0 180px; }
.task-view-toolbar { padding: 20px; }
#task { display: block; margin: 30px; width: 120px; height: 44px; }
[role=tooltip] { position: fixed; top: 10px; right: 10px; }
</style><section id="browser-banner">
<span>想要更好的 <b>飞书网页版体验</b>？</span><span>试试这些浏览器吧</span>
<button aria-label="关闭">×</button></section>
<main class="appLayout-content"><div id="root-todo"><div class="layout">
<aside><a href="/next/task/my-tasks">mine</a><a href="/next/task/watched-tasks">watched</a></aside>
<main><div class="task-view-toolbar">Tasks</div><button id="task">Open sample task</button>
<div role="alert">Sample error remains visible</div></main></div></div></main>
<div role="tooltip">Sample hover description</div>
<script>
window.clicked = 0; window.layoutRefreshes = 0;
document.querySelector('#task').onclick = () => window.clicked++;
document.querySelector('#browser-banner button').onclick = () => document.querySelector('#browser-banner').remove();
addEventListener('resize', () => window.layoutRefreshes++);
</script>'''


def main():
    errors = []
    cases = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=['--disable-dev-shm-usage'])
        try:
            for dpr in [1, 2]:
                context = browser.new_context(device_scale_factor=dpr, service_workers='block')
                context.route('**/*', lambda route: route.fulfill(body=FIXTURE, content_type='text/html'))
                try:
                    for embedded in [False, True]:
                        page = context.new_page()
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.goto(URL)
                        page.evaluate('(embedded) => window.__inspireTaskOptions = {embedded}', embedded)
                        page.add_script_tag(content=SCRIPT)
                        expect(page.locator('#browser-banner')).to_have_count(0)
                        for width in [520, 1200]:
                            page.set_viewport_size({'width': width, 'height': 1000})
                            for zoom in [0.8, 1, 1.25, 1.5, 2]:
                                previous = page.evaluate('window.layoutRefreshes')
                                page.evaluate('(zoom) => document.documentElement.style.zoom = zoom', zoom)
                                # ResizeObserver should refresh the task layout after zoom/resize.
                                page.wait_for_function('(previous) => window.layoutRefreshes > previous', arg=previous)
                                page.locator('#task').scroll_into_view_if_needed()
                                bounds = page.locator('#task').bounding_box()
                                x = bounds['x'] + bounds['width'] / 2
                                y = bounds['y'] + bounds['height'] / 2
                                page.mouse.move(x, y)
                                assert page.evaluate('([x, y]) => document.elementFromPoint(x, y).id', [x, y]) == 'task'
                                expect(page.locator('[role=tooltip]')).to_have_css('visibility', 'hidden')
                                before = page.evaluate('window.clicked')
                                page.mouse.click(x, y)
                                assert page.evaluate('window.clicked') == before + 1
                                expect(page.locator('[role=alert]')).to_be_visible()
                                page.evaluate('window.InspireTaskAppearance.setHideHover(false)')
                                expect(page.locator('[role=tooltip]')).to_have_css('visibility', 'visible')
                                page.evaluate('window.InspireTaskAppearance.setHideHover(true)')
                                page.keyboard.press('Tab')
                                expect(page.locator('[role=tooltip]')).to_have_css('visibility', 'visible')
                                cases += 1
                        page.close()
                finally:
                    context.close()
        finally:
            browser.close()
    assert not errors, errors
    print(f'PASS: {cases} cases; both layouts, CSS zoom 80–200%, DPR 1/2, narrow/wide; no page errors')


if __name__ == '__main__':
    main()
