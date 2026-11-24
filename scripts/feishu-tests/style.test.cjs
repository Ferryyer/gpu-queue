const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {JSDOM} = require('jsdom');
const source = readFileSync(require('node:path').join(__dirname, '../../serverbox/assets/feishu/inspire-task.user.js'), 'utf8');
// Synthetic content only. Structure follows the observed route-link/sidebar
// relationship; deliberately no hashed Feishu classes or private task content.
const fixture = `<section class="appNavbar">global</section><main class="appLayout-content"><div id="root-todo"><div><div class="layout"><aside><a href="/next/task/my-tasks">mine</a><a href="/next/task/watched-tasks">watched</a></aside><main><div class="task-view-toolbar"><button>new task</button></div><div role="checkbox" tabindex="0">sample</div></main></div></div></div></main>`;
function page(path = '/next/task/my-tasks', html = fixture, origin = 'https://uqyv5nolng8.feishu.cn', options = {embedded: true}) {
  const dom = new JSDOM(html, {url: origin + path, runScripts: 'outside-only'});
  const {window} = dom;
  let tick;
  let frames = [];
  let resize;
  const observed = new Set();
  window.ResizeObserver = class {
    constructor(callback) { resize = callback; }
    observe(target) { observed.add(target); }
    disconnect() { observed.clear(); }
  };
  window.visualViewport = new window.EventTarget();
  window.__inspireTaskOptions = {enabled: true, ...options};
  window.requestAnimationFrame = callback => { frames.push(callback); };
  window.setInterval = callback => { tick = callback; };
  window.matchMedia = () => ({matches: false, addEventListener() {}});
  window.eval(source);
  return {window, document: window.document, observed, resize: () => resize(), tick: () => tick?.(), frame: () => { const pending = frames; frames = []; pending.forEach(f => f()); }, close: () => window.close()};
}
test('task-only styling, SPA exit and return, one injected style', () => {
  const p = page();
  try {
    assert(p.document.documentElement.hasAttribute('data-inspire-task'));
    assert.equal(p.document.querySelectorAll('#inspire-task-style').length, 1);
    p.window.eval(source); p.tick();
    assert.equal(p.document.querySelectorAll('#inspire-task-style').length, 1);
    p.window.history.pushState({}, '', '/next/messenger'); p.tick();
    assert(!p.document.documentElement.hasAttribute('data-inspire-task'));
    p.window.history.pushState({}, '', '/next/task/watched-tasks'); p.tick();
    assert(p.document.documentElement.hasAttribute('data-inspire-task'));
    p.window.history.pushState({}, '', '/next/tasking'); p.tick();
    assert(!p.document.documentElement.hasAttribute('data-inspire-task'));
  } finally { p.close(); }
});
test('original appearance and dark mode toggle without touching task controls', () => {
  const p = page();
  try {
    const checkbox = p.document.querySelector('[role=checkbox]');
    p.window.InspireTaskAppearance.setEnabled(false);
    assert(!p.document.documentElement.hasAttribute('data-inspire-task'));
    p.window.InspireTaskAppearance.setEnabled(true);
    p.window.InspireTaskAppearance.setDark(true);
    assert(p.document.documentElement.hasAttribute('data-inspire-dark'));
    assert.equal(p.document.querySelector('[role=checkbox]'), checkbox);
  } finally { p.close(); }
});
test('navigation opens, Escape returns focus, selecting a route closes it', () => {
  const p = page();
  try {
    const button = p.document.querySelector('#inspire-task-nav-toggle');
    assert(button);
    button.click();
    assert.equal(button.getAttribute('aria-expanded'), 'true');
    p.document.dispatchEvent(new p.window.KeyboardEvent('keydown', {key: 'Escape'}));
    assert.equal(button.getAttribute('aria-expanded'), 'false');
    assert.equal(p.document.activeElement, button);
    button.click();
    p.document.querySelector('a').dispatchEvent(new p.window.MouseEvent('click', {bubbles: true}));
    assert.equal(button.getAttribute('aria-expanded'), 'false');
  } finally { p.close(); }
});
test('late-mounted or replaced roots are discovered without duplicates', () => {
  const p = page('/next/task/my-tasks', '');
  try {
    p.document.body.innerHTML = fixture; p.tick();
    assert(p.document.documentElement.hasAttribute('data-inspire-nav-ready'));
    p.document.body.innerHTML = fixture; p.tick(); p.tick();
    assert.equal(p.document.querySelectorAll('#inspire-task-nav-toggle').length, 1);
  } finally { p.close(); }
});
test('unknown layouts keep original navigation and login pages remain unchanged', () => {
  const p = page('/next/task/my-tasks', '<div id="root-todo"><nav>new layout</nav></div>');
  const login = page('/accounts/login');
  const other = page('/next/task/my-tasks', fixture, 'https://example.com');
  try {
    assert(!p.document.documentElement.hasAttribute('data-inspire-nav-ready'));
    assert(!login.document.documentElement.hasAttribute('data-inspire-task'));
    assert(!other.window.InspireTaskAppearance);
    assert.equal(other.document.querySelectorAll('style').length, 0);
  } finally { p.close(); login.close(); other.close(); }
});

test('standalone keeps original task positioning; only embedded mode adapts navigation', () => {
  const full = page('/next/task/my-tasks', fixture, undefined, {embedded: false});
  const compact = page();
  try {
    assert(full.document.documentElement.hasAttribute('data-inspire-task'));
    assert(!full.document.documentElement.hasAttribute('data-inspire-embedded'));
    assert.equal(full.document.querySelector('#inspire-task-nav-toggle'), null);
    assert.equal(full.document.querySelector('[data-inspire-task-layout]'), null);
    assert.notEqual(full.window.getComputedStyle(full.document.querySelector('#root-todo')).position, 'relative');
    assert(compact.document.documentElement.hasAttribute('data-inspire-embedded'));
    assert(compact.document.querySelector('#inspire-task-nav-toggle'));
    assert.equal(compact.window.getComputedStyle(compact.document.querySelector('#root-todo')).position, 'relative');
    let resizes = 0;
    full.window.addEventListener('resize', () => resizes++);
    full.window.InspireTaskAppearance.setEnabled(false);
    assert.equal(resizes, 0);
    full.frame(); assert.equal(resizes, 0);
    full.frame(); assert.equal(resizes, 1);
  } finally { full.close(); compact.close(); }
});

test('browser recommendation uses its close action, without hiding layout shells or task content', () => {
  const banner = '<section id="browser-banner"><div><span>想要更好的飞书网页版体验？</span><span>试试这些浏览器吧</span></div><button aria-label="关闭"><svg></svg></button></section>';
  const p = page('/next/task/my-tasks', banner + '<div role="alert"><button aria-label="关闭">网络中断，请重试</button></div>' + fixture);
  const login = page('/accounts/login', banner);
  const early = page('/next/task/my-tasks', '<div id="root-web-framework-application"><section class="appLayout">' + banner + '</section></div>');
  try {
    let closed = 0, otherClosed = 0, taskClosed = 0;
    p.document.querySelector('#browser-banner button').onclick = () => {
      closed++; p.document.querySelector('#browser-banner').remove();
    };
    p.document.querySelector('[role=alert] button').onclick = () => otherClosed++;
    const task = p.document.createElement('div');
    task.innerHTML = banner;
    task.querySelector('button').onclick = () => taskClosed++;
    p.document.querySelector('#root-todo').append(task);
    p.tick();
    assert.equal(closed, 1);
    assert.equal(otherClosed, 0);
    assert.equal(taskClosed, 0);
    assert(p.document.querySelector('[role=alert]'));
    assert.equal(p.document.querySelectorAll('[data-inspire-browser-tip]').length, 0);
    assert(p.document.querySelector('#inspire-task-style').textContent.includes('html[data-inspire-task-page] [data-inspire-browser-tip] { display: none'));
    assert(login.document.querySelector('#browser-banner'));
    early.document.querySelector('#browser-banner button').onclick = () => early.document.querySelector('#browser-banner').remove();
    early.tick();
    assert(early.document.querySelector('.appLayout'));
    assert(early.document.querySelector('#root-web-framework-application'));
    assert.equal(early.document.querySelector('#browser-banner'), null);
    p.window.InspireTaskAppearance.setEnabled(false);
    p.document.body.insertAdjacentHTML('afterbegin', banner);
    p.document.querySelector('#browser-banner button').onclick = () => p.document.querySelector('#browser-banner').remove();
    p.tick();
    assert.equal(p.document.body.firstElementChild.id, '');
    p.window.history.pushState({}, '', '/next/messenger'); p.tick();
    assert(!p.document.documentElement.hasAttribute('data-inspire-task-page'));
  } finally { p.close(); login.close(); early.close(); }
});

for (const embedded of [false, true]) {
  test(`split browser recommendation closes or falls back safely (embedded=${embedded})`, () => {
    const banner = '<section id="browser-banner"><span>想要更好的 <b>飞书网页版体验</b>？</span><span>试试这些浏览器吧</span><button aria-label="关闭"></button></section>';
    const p = page('/next/task/my-tasks', banner + fixture, undefined, {embedded, enabled: false});
    try {
      const tip = p.document.querySelector('#browser-banner');
      let clicks = 0;
      tip.querySelector('button').onclick = () => clicks++;
      for (let i = 0; i < 10; i++) p.tick();
      assert.equal(clicks, 2); // Initial pre-hydration click counts as attempt one.
      assert.equal(p.window.getComputedStyle(tip).display, 'none');
      assert.equal(p.document.querySelector('#root-todo').hasAttribute('data-inspire-browser-tip'), false);
      p.window.history.pushState({}, '', '/accounts/login'); p.tick();
      assert.notEqual(p.window.getComputedStyle(tip).display, 'none');
      p.window.history.pushState({}, '', '/next/task/my-tasks'); p.tick();
      assert.equal(p.window.getComputedStyle(tip).display, 'none');
    } finally { p.close(); }
  });

  test(`recommendation without close control leaves tasks and errors visible (embedded=${embedded})`, () => {
    const banner = '<section id="browser-banner">想要更好的飞书网页版体验？试试这些浏览器吧</section>';
    const p = page('/next/task/my-tasks', '<div class="appLayout">' + banner + fixture + '<div role="alert">网络错误</div></div>', undefined, {embedded});
    try {
      assert.equal(p.window.getComputedStyle(p.document.querySelector('#browser-banner')).display, 'none');
      for (const selector of ['.appLayout', '#root-todo', '[role=alert]']) {
        assert.notEqual(p.window.getComputedStyle(p.document.querySelector(selector)).display, 'none');
      }
    } finally { p.close(); }
  });

  test(`hover fallback is reversible and preserves keyboard descriptions (embedded=${embedded})`, () => {
    const p = page('/next/task/my-tasks', fixture + '<div role="tooltip">Description</div><div role="dialog">Editor</div><div role="alert">Error</div>', undefined, {embedded});
    try {
      const tip = p.document.querySelector('[role=tooltip]');
      const move = new p.window.Event('pointermove', {bubbles: true});
      Object.defineProperty(move, 'pointerType', {value: 'mouse'});
      p.document.dispatchEvent(move);
      assert.equal(p.window.getComputedStyle(tip).visibility, 'hidden');
      for (const role of ['dialog', 'alert', 'checkbox']) {
        assert.equal(p.window.getComputedStyle(p.document.querySelector(`[role=${role}]`)).visibility, 'visible');
      }
      p.window.InspireTaskAppearance.setEnabled(false);
      assert.equal(p.window.getComputedStyle(tip).visibility, 'hidden');
      p.window.InspireTaskAppearance.setHideHover(false);
      assert.equal(p.window.getComputedStyle(tip).visibility, 'visible');
      p.window.InspireTaskAppearance.setHideHover(true);
      p.document.dispatchEvent(new p.window.KeyboardEvent('keydown', {key: 'Tab'}));
      assert.equal(p.window.getComputedStyle(tip).visibility, 'visible');
      p.document.dispatchEvent(move);
      p.window.history.pushState({}, '', '/next/messenger'); p.tick();
      assert.equal(p.window.getComputedStyle(tip).visibility, 'visible');
    } finally { p.close(); }
  });
}

test('root size and visual viewport changes coalesce, and SPA replacement updates observation', () => {
  const p = page();
  try {
    let resizes = 0;
    p.window.addEventListener('resize', () => resizes++);
    p.frame(); p.frame();
    resizes = 0;
    assert(p.observed.has(p.document.querySelector('#root-todo')));
    p.resize(); p.resize();
    p.window.visualViewport.dispatchEvent(new p.window.Event('resize'));
    p.frame(); assert.equal(resizes, 0);
    p.frame(); assert.equal(resizes, 1);
    p.frame(); p.frame(); assert.equal(resizes, 1);
    const oldRoot = p.document.querySelector('#root-todo');
    p.document.body.innerHTML = fixture; p.tick();
    assert(!p.observed.has(oldRoot));
    assert(p.observed.has(p.document.querySelector('#root-todo')));
    p.window.history.pushState({}, '', '/accounts/login'); p.tick();
    assert.equal(p.observed.size, 0);
    p.frame(); p.frame(); resizes = 0;
    p.window.visualViewport.dispatchEvent(new p.window.Event('resize'));
    p.frame(); p.frame(); assert.equal(resizes, 0);
  } finally { p.close(); }
});
