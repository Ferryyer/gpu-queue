// ==UserScript==
// @name         Inspire Queue · 飞书任务
// @namespace    local.feishu.task
// @version      2.0.3
// @description  隐藏全局导航，暖白与陶土色主题，小窗口可展开任务导航。
// @match        https://uqyv5nolng8.feishu.cn/*
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @run-at       document-start
// ==/UserScript==

// Based on the user's “飞书任务：隐藏全局导航” v1.1.0.
(() => {
  'use strict';
  if (location.origin !== 'https://uqyv5nolng8.feishu.cn' || window.top !== window) return;
  if (window.InspireTaskAppearance) return;
  const attribute = 'data-inspire-task';
  const native = window.__inspireTaskOptions;
  let enabled = native ? native.enabled !== false :
    (typeof GM_getValue === 'function' ? GM_getValue('hideGlobalNav', true) : true);
  let dark = native ? native.dark === true : matchMedia('(prefers-color-scheme: dark)').matches;
  let open = false;
  let lastPath = '';
  let nav = null;
  let button = null;
  const style = document.createElement('style');
  style.id = 'inspire-task-style';
  style.textContent = `
    html[${attribute}] {
      --iq-bg: #faf9f6; --iq-panel: #ffffff; --iq-nav: #f0eee8;
      --iq-text: #292722; --iq-muted: #716d65; --iq-line: #e5e1d8;
      --iq-accent: #ae583f; --iq-selected: #f4e8e2; --iq-hover: #eeeae2;
      --iq-on-accent: #ffffff; --iq-accent-hover: #934a35;
      color-scheme: light;
    }
    html[${attribute}][data-inspire-dark] {
      --iq-bg: #222321; --iq-panel: #292a27; --iq-nav: #1d1e1c;
      --iq-text: #ecece7; --iq-muted: #abada5; --iq-line: #41433c;
      --iq-accent: #de947a; --iq-selected: #42332e; --iq-hover: #343630;
      --iq-on-accent: #222321; --iq-accent-hover: #ecaa93;
      color-scheme: dark;
    }
    html[${attribute}] .appNavbar { display: none !important; }
    html[${attribute}] .appLayout-content {
      padding: 0 !important; background: var(--iq-bg) !important; min-width: 0 !important;
    }
    html[${attribute}] #root-todo {
      border-radius: 0 !important; background: var(--iq-bg) !important;
      color: var(--iq-text); position: relative; box-sizing: border-box;
      font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif;
    }
    html[${attribute}], html[${attribute}] body * {
      --bg-body: var(--iq-bg) !important; --bg-base: var(--iq-nav) !important;
      --bg-float: var(--iq-panel) !important; --bg-float-base: var(--iq-nav) !important;
      --bg-float-overlay: var(--iq-hover) !important; --bg-body-overlay: var(--iq-hover) !important;
      --bg-content-base: var(--iq-bg) !important; --bg-sub-navigation: var(--iq-nav) !important;
      --text-title: var(--iq-text) !important; --text-caption: var(--iq-muted) !important;
      --text-placeholder: var(--iq-muted) !important; --text-link-normal: var(--iq-accent) !important;
      --primary-fill-default: var(--iq-accent) !important;
      --primary-content-default: var(--iq-accent) !important;
      --primary-on-primary-fill: var(--iq-on-accent) !important;
      --primary-fill-hover: var(--iq-accent-hover) !important; --primary-fill-pressed: var(--iq-accent-hover) !important;
      --primary-content-hover: var(--iq-accent-hover) !important; --primary-content-pressed: var(--iq-accent-hover) !important;
      --primary-fill-transparent-01: var(--iq-selected) !important;
      --primary-fill-transparent-02: var(--iq-selected) !important;
      --primary-fill-transparent-03: var(--iq-selected) !important;
      --primary-fill-solid-01: var(--iq-selected) !important;
      --primary-fill-solid-02: var(--iq-selected) !important;
      --primary-fill-solid-03: var(--iq-selected) !important;
      --text-link-hover: var(--iq-accent-hover) !important; --text-link-pressed: var(--iq-accent-hover) !important;
      --udtoken-btn-se-bg-pri-hover: var(--iq-selected) !important;
      --udtoken-btn-se-bg-pri-focus: var(--iq-selected) !important;
      --udtoken-btn-se-bg-pri-pressed: var(--iq-hover) !important;
      --udtoken-btn-text-bg-pri-hover: var(--iq-selected) !important;
      --udtoken-btn-text-bg-pri-focus: var(--iq-selected) !important;
      --udtoken-btn-text-bg-pri-pressed: var(--iq-hover) !important;
      --primary-pri-500: var(--iq-accent) !important; --primary-pri-100: var(--iq-selected) !important;
      --fill-hover: var(--iq-hover) !important; --fill-selected: var(--iq-selected) !important;
      --fill-active: var(--iq-selected) !important; --fill-focus: var(--iq-hover) !important;
      --line-divider-default: var(--iq-line) !important; --line-border-card: var(--iq-line) !important;
      --line-border-component: var(--iq-line) !important; --line-divider-module: var(--iq-line) !important;
    }
    html[${attribute}] [data-inspire-task-layout] { position: relative !important; }
    html[${attribute}] [data-inspire-task-nav] { background: var(--iq-nav) !important; }
    html[${attribute}] [data-inspire-task-nav] a:hover { background: var(--iq-hover) !important; }
    html[${attribute}] [data-inspire-task-nav] a[aria-current="page"] {
      background: var(--iq-selected) !important; color: var(--iq-accent) !important;
    }
    html[${attribute}] [data-inspire-task-main] { min-width: 0 !important; flex: 1 1 0 !important; }
    html[${attribute}] #root-todo button { border-radius: 7px; }
    html[${attribute}] #root-todo a:focus-visible,
    html[${attribute}] #root-todo button:focus-visible { outline: 2px solid var(--iq-accent); outline-offset: 2px; }
    #inspire-task-nav-toggle { display: none; }
    html[data-inspire-task-page] [data-inspire-browser-tip] { display: none !important; }
    @media (max-width: 760px) {
      html[${attribute}][data-inspire-nav-ready] #root-todo { padding-top: 44px !important; }
      html[${attribute}][data-inspire-nav-ready] #inspire-task-nav-toggle {
        display: inline-flex; align-items: center; position: absolute; top: 6px; left: 12px;
        z-index: 101; height: 32px; padding: 0 12px; border: 1px solid var(--iq-line);
        background: var(--iq-panel); color: var(--iq-text); font: inherit; font-size: 13px;
        cursor: pointer;
      }
      html[${attribute}] [data-inspire-task-nav] { display: none !important; }
      html[${attribute}][data-inspire-nav-open] [data-inspire-task-nav] {
        display: flex !important; position: absolute !important; left: 0; top: 0; bottom: 0;
        width: min(260px, 85%) !important; height: auto !important;
        z-index: 100; box-shadow: 8px 0 24px #0002;
      }
      html[${attribute}] .task-view-toolbar { flex-wrap: wrap; row-gap: 6px; }
    }
  `;

  function closeNav() { open = false; sync(); }
  function hideBrowserSuggestion() {
    if (!document.body) return;
    // Only the product's browser recommendation, never task text or other alerts.
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT, {
      acceptNode(node) {
        if (node.matches('#root-todo, .appNavbar, script, style, [data-inspire-browser-tip]')) {
          return NodeFilter.FILTER_REJECT;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    let node;
    while ((node = walker.nextNode())) {
      const ownText = [...node.childNodes].filter(n => n.nodeType === Node.TEXT_NODE)
        .map(n => n.textContent).join('');
      if (!ownText.includes('想要更好的飞书网页版体验')) continue;
      let banner = node;
      for (let depth = 0; banner && depth < 5; depth++, banner = banner.parentElement) {
        const text = banner.textContent.trim();
        if (text.length > 180 || banner.querySelector('#root-todo')) break;
        if (text.includes('试试这些浏览器吧') && banner.querySelector('a')) {
          while (banner.parentElement && banner.parentElement !== document.body &&
                 !banner.parentElement.querySelector('#root-todo') &&
                 banner.parentElement.textContent.trim() === text) banner = banner.parentElement;
          banner.setAttribute('data-inspire-browser-tip', '');
          window.dispatchEvent(new Event('resize'));
          break;
        }
      }
    }
  }
  function locateNavigation(root) {
    if (nav && root.contains(nav) && button && root.contains(button)) return;
    // Route links identify the navigation without depending on hashed CSS.
    // If Feishu changes the structure, leave the original navigation visible.
    const link = root.querySelector('a[href$="/next/task/my-tasks"]');
    if (!link) return;
    let candidate = link.parentElement;
    while (candidate && candidate !== root) {
      const sibling = candidate.nextElementSibling;
      if (sibling && candidate.querySelector('a[href$="/next/task/watched-tasks"]') &&
          sibling.querySelector('.task-view-toolbar')) {
        nav = candidate;
        nav.parentElement.setAttribute('data-inspire-task-layout', '');
        nav.setAttribute('data-inspire-task-nav', '');
        nav.id ||= 'inspire-task-navigation';
        sibling.setAttribute('data-inspire-task-main', '');
        button = document.getElementById('inspire-task-nav-toggle');
        if (!button) {
          button = document.createElement('button');
          button.id = 'inspire-task-nav-toggle';
          button.type = 'button';
          button.addEventListener('click', () => { open = !open; sync(); });
          root.prepend(button);
        }
        button.setAttribute('aria-controls', nav.id);
        return;
      }
      candidate = candidate.parentElement;
    }
    nav = null;
  }
  function sync() {
    const html = document.documentElement;
    if (!html) return;
    if (!style.isConnected) html.append(style);
    const taskPage = /^\/next\/task(?:\/|$)/.test(location.pathname);
    const active = enabled && taskPage;
    html.toggleAttribute('data-inspire-task-page', taskPage);
    if (taskPage) hideBrowserSuggestion();
    const wasActive = html.hasAttribute(attribute);
    html.toggleAttribute(attribute, active);
    html.toggleAttribute('data-inspire-dark', active && dark);
    if (lastPath !== location.pathname) { open = false; lastPath = location.pathname; }
    const root = active ? document.querySelector('#root-todo') : null;
    if (root) locateNavigation(root);
    const ready = !!(root && nav && root.contains(nav));
    const wasReady = html.hasAttribute('data-inspire-nav-ready');
    html.toggleAttribute('data-inspire-nav-ready', ready);
    html.toggleAttribute('data-inspire-nav-open', ready && open);
    if (button) {
      const label = open ? '收起任务导航' : '☰ 任务导航';
      if (button.textContent !== label) button.textContent = label;
      button.setAttribute('aria-expanded', String(open));
    }
    if (active !== wasActive || ready !== wasReady) window.dispatchEvent(new Event('resize'));
  }
  window.InspireTaskAppearance = {
    setEnabled(value) { enabled = value === true; sync(); },
    setDark(value) { dark = value === true; sync(); }
  };
  if (typeof GM_registerMenuCommand === 'function') {
    GM_registerMenuCommand('切换：Inspire 风格 / 飞书原版', () => {
      enabled = !enabled;
      if (typeof GM_setValue === 'function') GM_setValue('hideGlobalNav', enabled);
      sync();
    });
  }
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && open) { closeNav(); button?.focus(); }
  });
  document.addEventListener('click', event => {
    if (open && nav && event.target instanceof Element &&
        (event.target.closest('a') || (!nav.contains(event.target) && !button?.contains(event.target)))) closeNav();
  });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', event => {
    if (!native) { dark = event.matches; sync(); }
  });
  sync();
  // SPA routing and asynchronously mounted roots; never reads task content,
  // cookies, or tokens, and never sends any data.
  setInterval(sync, 500);
})();
