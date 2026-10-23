// DOC Docs HUD. Injected into every scene page before its own scripts, so
// everything it draws is in the recorded frames, timed by the same clock as
// the narration. Two fixed layers, outside the page's own layout:
//   fx   moves with the page when it zooms: layout-shift outlines
//   hud  stays put: labels, captions, badges, the fade-through-navy cover
// The recorder drives it through window.__docdocsHud.
(() => {
  const cfg = window.__docdocs || {};
  if (window.top !== window) {
    // Inside the phone frame: report shifts to the top frame, which draws them.
    if (cfg.layoutShift && 'PerformanceObserver' in window) {
      new PerformanceObserver((list) => {
        let frameEl;
        try { frameEl = window.frameElement; } catch (e) { return; }
        const top = window.top.__docdocsHud;
        if (!frameEl || !top) return;
        const fr = frameEl.getBoundingClientRect();
        const k = fr.width / window.innerWidth;
        const map = (r) => r && { x: fr.left + r.x * k, y: fr.top + r.y * k, width: r.width * k, height: r.height * k };
        for (const e of list.getEntries()) {
          if (e.hadRecentInput) continue;
          top.shift(e.value, (e.sources || []).map((s) => [map(s.previousRect), map(s.currentRect)]));
        }
      }).observe({ type: 'layout-shift', buffered: true });
    }
    return;
  }
  const C = { amber: '#F59E0B', cyan: '#00C8FF', navy: '#080A0F', text: '#E8EAF0', muted: '#8B93A1', rose: '#F43F5E' };
  const state = { label: null, caption: null, speed: null, zoom: null, covered: false };
  let fx, hud, labelEl, captionEl, badgeEl, speedEl, clsEl, bigEl, cover;
  let cls = 0;

  const css = `
    ${cfg.fontCss || ''}
    #dd-fx, #dd-hud { position: fixed; inset: 0; pointer-events: none; z-index: 2147483646; }
    #dd-hud { z-index: 2147483647; --u: min(1vw, 1vh); }
    #dd-fx { transform-origin: 0 0; transition: transform var(--zoom-ms, 700ms) cubic-bezier(.3,.7,.2,1); }
    .dd-label { position: absolute; left: 50%; top: calc(var(--u) * 6); transform: translate(-50%, calc(var(--u) * 1.5));
      opacity: 0; transition: opacity 260ms ease-out, transform 360ms cubic-bezier(.2,.7,.2,1);
      font: 400 calc(var(--u) * 4.4)/1.2 'DD Literata', Georgia, serif; color: ${C.text}; letter-spacing: -0.01em;
      text-align: center; max-width: 86vw; white-space: pre-wrap; text-shadow: 0 2px 18px rgb(0 0 0 / .45); }
    .dd-label.on { opacity: 1; transform: translate(-50%, 0); }
    .dd-label.backdrop { background: rgb(8 10 15 / .86); padding: calc(var(--u) * 1.2) calc(var(--u) * 2.6);
      border-radius: calc(var(--u) * 1.6); border: 1px solid rgb(255 255 255 / .08); backdrop-filter: blur(6px); }
    .dd-label em { font-style: normal; color: ${C.amber}; }
    .dd-label em.cyan { color: ${C.cyan}; }
    .dd-caption { position: absolute; left: 50%; bottom: calc(var(--u) * 5); transform: translateX(-50%);
      max-width: 88vw; text-align: center; font: 800 calc(var(--u) * 4)/1.2 'DD Syne', sans-serif; color: ${C.text};
      background: rgb(8 10 15 / .78); padding: calc(var(--u) * 1) calc(var(--u) * 2.2); border-radius: calc(var(--u) * 1.4); }
    .dd-caption:empty { display: none; }
    @media (orientation: portrait) { .dd-caption { bottom: 5vh; font-size: calc(var(--u) * 4.6); max-width: 92vw; } .dd-label { top: calc(var(--u) * 12); font-size: calc(var(--u) * 6.4); } }
    .dd-caption span { opacity: .55; transition: opacity 90ms linear, color 90ms linear; }
    .dd-caption span.said { opacity: 1; }
    .dd-caption span.now { opacity: 1; color: ${C.cyan}; }
    .dd-pill { position: absolute; padding: calc(var(--u) * .8) calc(var(--u) * 1.6); border-radius: 999px;
      font: 700 calc(var(--u) * 2)/1 'DD Mono', ui-monospace, monospace; letter-spacing: .1em; color: ${C.navy}; }
    .dd-cover { position: absolute; inset: 0; background: ${C.navy}; opacity: 0; transition: opacity var(--cover-ms, 320ms) ease-in-out; }
    .dd-cover.on { opacity: 1; }
    .dd-shift { position: fixed; border-radius: 6px; transition: opacity 1.3s ease-out .5s; }
    .dd-shift.held { transition: opacity 600ms ease-out; }
    .dd-big { position: absolute; right: 9vw; top: 50%; transform: translateY(-50%); text-align: center; }
    .dd-big .v { font: 700 calc(var(--u) * 11)/1 'DD Mono', ui-monospace, monospace; color: ${C.amber}; }
    .dd-big .v.after { color: ${C.cyan}; }
    .dd-big .k { font: 700 calc(var(--u) * 2.2)/1 'DD Mono', ui-monospace, monospace; letter-spacing: .16em; color: ${C.muted}; margin-top: calc(var(--u) * 1.6); }
  `;

  function build() {
    if (hud || !document.documentElement) return !!hud;
    const style = document.createElement('style');
    style.textContent = css;
    fx = document.createElement('div'); fx.id = 'dd-fx';
    hud = document.createElement('div'); hud.id = 'dd-hud';
    labelEl = document.createElement('div'); labelEl.className = 'dd-label' + (cfg.labelBackdrop ? ' backdrop' : '');
    captionEl = document.createElement('div'); captionEl.className = 'dd-caption';
    cover = document.createElement('div'); cover.className = 'dd-cover';
    hud.append(labelEl, captionEl, cover);
    document.documentElement.append(style, fx, hud);
    if (cfg.badge) badgeEl = pill(cfg.badge, cfg.badgeTone === 'after' ? C.cyan : C.amber, 'top', 'right');
    if (cfg.layoutShift && !cfg.bigCounter) clsEl = pill('CLS 0.000', cfg.badgeTone === 'after' ? C.cyan : C.amber, 'top', 'left');
    if (cfg.layoutShift && cfg.bigCounter) {
      bigEl = document.createElement('div');
      bigEl.className = 'dd-big';
      bigEl.innerHTML = `<div class="v ${cfg.badgeTone === 'after' ? 'after' : ''}">0.000</div><div class="k">LAYOUT SHIFT</div>`;
      hud.insertBefore(bigEl, cover);
    }
    replay();
    return true;
  }

  function pill(text, color, v, h) {
    const el = document.createElement('div');
    el.className = 'dd-pill';
    el.textContent = text;
    el.style.background = color;
    el.style[v] = 'calc(var(--u) * 2.4)';
    el.style[h] = 'calc(var(--u) * 2.4)';
    hud.insertBefore(el, cover);
    return el;
  }

  // "loudest = *brightest*" -> accent on brightest; "_word_" -> cyan accent.
  function markup(text) {
    const esc = (s) => s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]);
    return esc(text).replace(/\*(.+?)\*/g, '<em>$1</em>').replace(/_(.+?)_/g, '<em class="cyan">$1</em>');
  }

  function setLabel(text) {
    state.label = text;
    if (!build()) return;
    if (!text) { labelEl.classList.remove('on'); return; }
    if (labelEl.dataset.text === text && labelEl.classList.contains('on')) return;
    labelEl.classList.remove('on');
    labelEl.dataset.text = text;
    labelEl.innerHTML = markup(text);
    void labelEl.offsetWidth;
    labelEl.classList.add('on');
  }

  // chunks: [{words: [...], times: [[start, end] ms from t0, ...]}]
  let captionRaf = 0;
  function setCaption(spec) {
    state.caption = spec;
    if (!build()) return;
    cancelAnimationFrame(captionRaf);
    captionEl.innerHTML = '';
    if (!spec) return;
    let shown = -1;
    const tick = () => {
      const t = Date.now() - spec.t0;
      const i = spec.chunks.findIndex((c) => t < c.times[c.times.length - 1][1] + 120);
      if (i === -1) { captionEl.innerHTML = ''; return; }
      const chunk = spec.chunks[i];
      if (i !== shown) {
        captionEl.innerHTML = chunk.words.map((w) => `<span>${w.replace(/[&<>]/g, '')}</span>`).join(' ');
        shown = i;
      }
      const spans = captionEl.children;
      chunk.times.forEach(([a, b], k) => {
        spans[k].className = t >= b ? 'said' : t >= a ? 'now' : '';
      });
      captionRaf = requestAnimationFrame(tick);
    };
    tick();
  }

  function setSpeed(factor) {
    state.speed = factor;
    if (!build()) return;
    if (speedEl) { speedEl.remove(); speedEl = null; }
    if (factor && factor !== 1) speedEl = pill(`${factor}× SPEED`, C.text, 'bottom', 'right');
  }

  function setCover(on, ms) {
    state.covered = on;
    if (!build()) return;
    cover.style.setProperty('--cover-ms', `${ms || 0}ms`);
    void cover.offsetWidth;
    cover.classList.toggle('on', on);
  }

  // Push the page (and the fx layer with it) towards an element.
  function setZoom(spec) {
    state.zoom = spec;
    if (!build()) return;
    const body = document.body;
    if (!body) return;
    body.style.transformOrigin = '0 0';
    body.style.transition = `transform ${spec ? spec.ms : 700}ms cubic-bezier(.3,.7,.2,1)`;
    fx.style.setProperty('--zoom-ms', `${spec ? spec.ms : 700}ms`);
    if (!spec) { body.style.transform = ''; fx.style.transform = ''; return; }
    const el = typeof spec.target === 'string' ? document.querySelector(spec.target) : null;
    const raw = el ? el.getBoundingClientRect() : spec.target; // or {left, top, width, height}
    if (!raw) return;
    const vw = innerWidth, vh = innerHeight;
    // Aim at the part of the target that is on screen, not at a centre far below the fold.
    const left = Math.max(raw.left, 0), top = Math.max(raw.top, 0);
    const right = Math.min(raw.left + raw.width, vw), bottom = Math.min(raw.top + raw.height, vh);
    const r = { left, top, width: Math.max(0, right - left), height: Math.max(0, bottom - top) };
    const s = spec.scale;
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const b = body.getBoundingClientRect();
    const tx = vw / 2 - s * cx, ty = vh / 2 - s * cy;
    fx.style.transform = `translate(${tx}px, ${ty}px) scale(${s})`;
    body.style.transform = `translate(${(s - 1) * b.left + tx}px, ${(s - 1) * b.top + ty}px) scale(${s})`;
  }

  function replay() {
    if (state.label) setLabel(state.label);
    if (state.caption) setCaption(state.caption);
    if (state.speed) setSpeed(state.speed);
    if (state.covered) setCover(true, 0);
  }

  // With holdShifts, outlines stay until clearShifts(), so the narration can point at them.
  function outline(rect, dashed) {
    if (!build() || !rect || (!rect.width && !rect.height)) return;
    const box = document.createElement('div');
    box.className = 'dd-shift' + (cfg.holdShifts ? ' held' : '');
    Object.assign(box.style, {
      left: `${rect.x}px`, top: `${rect.y}px`, width: `${rect.width}px`, height: `${rect.height}px`,
      border: `${dashed ? 2 : 3}px ${dashed ? 'dashed' : 'solid'} ${C.amber}`,
      background: dashed ? 'transparent' : 'rgb(245 158 11 / .16)', opacity: dashed && cfg.holdShifts ? '.55' : '1',
    });
    fx.appendChild(box);
    if (cfg.holdShifts) return;
    requestAnimationFrame(() => requestAnimationFrame(() => { box.style.opacity = '0'; }));
    setTimeout(() => box.remove(), 2200);
  }

  function shift(value, pairs) {
    cls += value;
    for (const [before, after] of pairs) { outline(before, true); outline(after, false); }
    if (!build()) return;
    if (clsEl) clsEl.textContent = `CLS ${cls.toFixed(3)}`;
    if (bigEl) bigEl.querySelector('.v').textContent = cls.toFixed(3);
  }

  function clearShifts() {
    if (!build()) return;
    for (const box of fx.querySelectorAll('.dd-shift')) { box.style.opacity = '0'; setTimeout(() => box.remove(), 700); }
  }

  // In the phone frame (bigCounter) the shifts come from the app's own frame;
  // here, only the page itself is watched, never the HUD's own elements.
  const ours = (node) => node && node.closest && node.closest('#dd-hud, #dd-fx');
  if (cfg.layoutShift && !cfg.bigCounter && 'PerformanceObserver' in window) {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (entry.hadRecentInput) continue;
        const sources = (entry.sources || []).filter((s) => !ours(s.node));
        if (entry.sources && entry.sources.length && !sources.length) continue;
        shift(entry.value, sources.map((s) => [s.previousRect, s.currentRect]));
      }
    }).observe({ type: 'layout-shift', buffered: true });
  }

  document.addEventListener('DOMContentLoaded', build);
  build();

  window.__docdocsHud = {
    label: setLabel,
    caption: setCaption,
    speed: setSpeed,
    cover: setCover,
    zoom: setZoom,
    shift,
    clearShifts,
    restore(saved) { Object.assign(state, saved); replay(); if (saved.zoom) setTimeout(() => setZoom(saved.zoom), 50); },
  };
})();
