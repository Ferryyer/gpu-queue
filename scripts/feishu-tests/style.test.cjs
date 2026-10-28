const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {JSDOM} = require('jsdom');
const source = readFileSync(require('node:path').join(__dirname, '../../serverbox/assets/feishu/inspire-task.user.js'), 'utf8');
// Synthetic content only. Structure follows the observed route-link/sidebar
// relationship; deliberately no hashed Feishu classes or private task content.
const fixture = `<section class="appNavbar">global</section><main class="appLayout-content"><div id="root-todo"><div><div class="layout"><aside><a href="/next/task/my-tasks">mine</a><a href="/next/task/watched-tasks">watched</a></aside><main><div class="task-view-toolbar"><button>new task</button></div><div role="checkbox" tabindex="0">sample</div></main></div></div></div></main>`;
function page(path = '/next/task/my-tasks', html = fixture, origin = 'https://uqyv5nolng8.feishu.cn') {
  const dom = new JSDOM(html, {url: origin + path, runScripts: 'outside-only'});
  const {window} = dom;
  let tick;
  window.setInterval = callback => { tick = callback; };
  window.matchMedia = () => ({matches: false, addEventListener() {}});
  window.eval(source);
  return {window, document: window.document, tick: () => tick?.(), close: () => window.close()};
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
