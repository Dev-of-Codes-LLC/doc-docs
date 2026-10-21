// DOC Docs overlay for browser scenes. Injected before the page's own
// scripts. It draws on a fixed layer the page cannot see or shift:
//   - a badge naming what is on screen (for example "BEFORE · SLOW 4G")
//   - with layoutShift on: every element the browser reports as shifted,
//     outlined where it landed, and a running CLS total
(() => {
  const cfg = window.__docdocs || {};
  const amber = '#F59E0B';
  const cyan = '#00C8FF';
  let layer;
  let clsEl;
  let cls = 0;

  function ensureLayer() {
    if (layer || !document.body) return layer;
    layer = document.createElement('div');
    layer.setAttribute('data-docdocs', 'overlay');
    layer.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:2147483647;';
    document.documentElement.appendChild(layer);
    const pill = (text, color, where) => {
      const el = document.createElement('div');
      el.textContent = text;
      el.style.cssText = `position:fixed;${where};padding:6px 12px;border-radius:999px;` +
        `font:700 13px/1.2 ui-monospace,Consolas,monospace;letter-spacing:.08em;` +
        `color:#080A0F;background:${color};box-shadow:0 2px 10px rgb(0 0 0 / .25);`;
      layer.appendChild(el);
      return el;
    };
    if (cfg.badge) pill(cfg.badge, cfg.badgeColor === 'after' ? cyan : amber, 'top:12px;right:12px');
    if (cfg.layoutShift) clsEl = pill('CLS 0.000', cfg.badgeColor === 'after' ? cyan : amber, 'bottom:12px;left:12px');
    return layer;
  }

  function outline(rect, dashed) {
    if (!ensureLayer() || !rect || (!rect.width && !rect.height)) return;
    const box = document.createElement('div');
    box.style.cssText = `position:fixed;left:${rect.x}px;top:${rect.y}px;width:${rect.width}px;height:${rect.height}px;` +
      `border:3px ${dashed ? 'dashed' : 'solid'} ${amber};border-radius:6px;` +
      `background:${dashed ? 'transparent' : 'rgb(245 158 11 / .16)'};transition:opacity 1.4s ease-out 0.6s;`;
    layer.appendChild(box);
    requestAnimationFrame(() => requestAnimationFrame(() => { box.style.opacity = '0'; }));
    setTimeout(() => box.remove(), 2200);
  }

  document.addEventListener('DOMContentLoaded', ensureLayer);

  if (cfg.layoutShift && 'PerformanceObserver' in window) {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (entry.hadRecentInput) continue;
        cls += entry.value;
        for (const source of entry.sources || []) {
          outline(source.previousRect, true);
          outline(source.currentRect, false);
        }
        if (ensureLayer() && clsEl) clsEl.textContent = `CLS ${cls.toFixed(3)}`;
      }
    }).observe({ type: 'layout-shift', buffered: true });
  }
})();
