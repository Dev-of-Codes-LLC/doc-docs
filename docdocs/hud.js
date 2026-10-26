// DOC Docs HUD. Injected into every scene page before its own scripts, so
// everything it draws is in the recorded frames, timed by the same clock as
// the narration. Two fixed layers, outside the page's own layout:
//   fx   moves with the page when it zooms: layout-shift outlines
//   hud  stays put: sheets, labels, captions, badges, the fade-through-navy cover
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
  const state = { label: null, caption: null, speed: null, zoom: null, covered: false, sheets: null, sheetsOp: null };
  let fx, hud, labelEl, captionEl, badgeEl, speedEl, clsEl, bigEl, cover, pile, scrim, smoke;
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
      width: max-content; max-width: 88vw; text-align: center; font: 800 calc(var(--u) * 4)/1.2 'DD Syne', sans-serif; color: ${C.text};
      background: rgb(8 10 15 / .78); padding: calc(var(--u) * 1) calc(var(--u) * 2.2); border-radius: calc(var(--u) * 1.4); }
    .dd-caption:empty { display: none; }
    @media (orientation: portrait) { .dd-caption { bottom: 5vh; font-size: calc(var(--u) * 4.6); max-width: 92vw; } .dd-label { top: calc(var(--u) * 12); font-size: calc(var(--u) * 6.4); } }
    .dd-caption span { opacity: .55; transition: opacity 90ms linear, color 90ms linear; }
    .dd-caption span.said { opacity: 1; }
    .dd-caption span.now { opacity: 1; color: ${C.cyan}; }
    /* captionStyle "plain": one quiet line in Literata, no word highlight, on an opaque plate so a busy page never shows through. */
    .dd-caption.plain { font: 600 calc(var(--u) * 4.6)/1.25 'DD Literata', Georgia, serif; letter-spacing: -0.005em;
      background: #0E1117; border: 1px solid rgb(255 255 255 / .1); box-shadow: 0 0 calc(var(--u) * 2) rgb(8 10 15 / .9); }
    .dd-caption.plain span, .dd-caption.plain span.now { opacity: 1; color: inherit; }
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
    .dd-big .live { font: 700 calc(var(--u) * 1.7)/1 'DD Mono', ui-monospace, monospace; letter-spacing: .2em; color: ${C.muted}; opacity: .75; margin-top: calc(var(--u) * 1.1); }
    /* Sheets: documents laid over the scene. */
    .dd-scrim { position: absolute; inset: 0; background: rgb(8 10 15 / .72); opacity: 0; transition: opacity 500ms ease-out; }
    .dd-scrim.on { opacity: 1; }
    .dd-pile { position: absolute; inset: 0; transition: transform 600ms cubic-bezier(.2,.8,.2,1), opacity 600ms ease-in; }
    .dd-pile.bundled { transform: scale(.88); }
    .dd-pile.shipped { transform: translate(70vw, -95vh) rotate(-9deg) scale(.6); opacity: 0;
      transition: transform 950ms cubic-bezier(.6,0,.9,.4), opacity 950ms cubic-bezier(.9,0,1,1); }
    .dd-pile.rumble { animation: dd-rumble 70ms linear infinite; }
    @keyframes dd-rumble { 0%, 100% { translate: 0 0; } 25% { translate: -3px 1.5px; } 50% { translate: 2.5px -2px; } 75% { translate: -1.5px -2.5px; } }
    .dd-smoke { position: absolute; inset: 0; pointer-events: none; }
    .dd-puff { position: absolute; border-radius: 50%; opacity: 0;
      background: radial-gradient(circle, rgb(232 234 240 / .8) 0, rgb(190 196 208 / .5) 35%, rgb(140 148 162 / .18) 58%, transparent 72%);
      animation: dd-puff var(--life, 1200ms) cubic-bezier(.2,.7,.3,1) var(--delay, 0ms) forwards; }
    @keyframes dd-puff { 0% { opacity: 0; transform: translate(0, 0) scale(.3); } 12% { opacity: .95; }
      100% { opacity: 0; transform: translate(var(--dx), var(--dy)) scale(var(--grow, 2.6)); } }
    .dd-pile.cleared { opacity: 0; }
    .dd-sheet { position: absolute; box-sizing: border-box; padding: calc(var(--u) * 2.2) calc(var(--u) * 2.6);
      border-radius: calc(var(--u) * 1.2); background: #161B24; border: 1px solid color-mix(in srgb, var(--tone) 50%, transparent);
      box-shadow: 0 calc(var(--u) * 1.6) calc(var(--u) * 5) rgb(0 0 0 / .6); transform-origin: 0 0;
      transition-property: left, top, width, transform, opacity; transition-duration: 650ms;
      transition-timing-function: cubic-bezier(.2,.8,.2,1); }
    .dd-sheet .k { font: 700 calc(var(--u) * 2.6)/1 'DD Mono', ui-monospace, monospace; letter-spacing: .14em; color: var(--tone); }
    .dd-sheet .t { font: 600 calc(var(--u) * 4.4)/1.15 'DD Literata', Georgia, serif; color: ${C.text};
      margin: calc(var(--u) * 1.3) 0 calc(var(--u) * 1.4); }
    .dd-sheet .l { font: 700 calc(var(--u) * var(--ls, 2.6))/1.55 'DD Mono', ui-monospace, monospace; color: ${C.muted};
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .dd-sheet .l.in { animation: dd-line 420ms ease-out both; }
    @keyframes dd-line { from { opacity: 0; transform: translateY(calc(var(--u) * 1)); } }
    .dd-strap { position: absolute; border-radius: 2px; opacity: 0; box-shadow: 0 2px 10px rgb(0 0 0 / .45);
      background: linear-gradient(var(--sheen, 180deg), #F4F5F8, #C9CED8 55%, #E8EAF0); transition: opacity 120ms ease-out, transform 420ms cubic-bezier(.3,.8,.3,1); }
    .dd-strap.h { transform: scaleX(0); transform-origin: 0 50%; --sheen: 180deg; }
    .dd-strap.v { transform: scaleY(0); transform-origin: 50% 0; transition-delay: 0ms, 220ms; --sheen: 90deg; }
    .dd-pile.bundled .dd-strap { opacity: 1; transform: none; }
    .dd-bow { position: absolute; width: 0; height: 0; transform: scale(0); }
    .dd-pile.tied .dd-bow { animation: dd-bow 420ms cubic-bezier(.3,1.6,.5,1) forwards; }
    @keyframes dd-bow { to { transform: scale(1); } }
    .dd-bow i { position: absolute; display: block; box-sizing: border-box; }
    .dd-bow .loop { width: var(--lw); height: var(--lh); top: calc(var(--lh) / -2); border: var(--t) solid #E8EAF0; border-radius: 50%;
      box-shadow: 0 2px 8px rgb(0 0 0 / .45), inset 0 0 0 1px rgb(255 255 255 / .2); }
    .dd-bow .loop.l { right: 0; transform-origin: 100% 50%; transform: rotate(-22deg); }
    .dd-bow .loop.r { left: 0; transform-origin: 0 50%; transform: rotate(22deg); }
    .dd-bow .tail { width: var(--t); height: calc(var(--lh) * 1.25); top: 0; transform-origin: 50% 0;
      background: linear-gradient(90deg, #C9CED8, #F4F5F8); box-shadow: 0 2px 8px rgb(0 0 0 / .4); }
    .dd-bow .tail.l { left: calc(var(--t) / -2); transform: rotate(28deg); } .dd-bow .tail.r { left: calc(var(--t) / -2); transform: rotate(-28deg); }
    .dd-bow .knot { width: calc(var(--t) * 2.2); height: calc(var(--t) * 2.2); left: calc(var(--t) * -1.1); top: calc(var(--t) * -1.1);
      border-radius: 40%; background: radial-gradient(circle at 35% 35%, #FFFFFF, #C9CED8 70%); box-shadow: 0 2px 8px rgb(0 0 0 / .5); }
    .dd-big .live::before { content: ''; display: inline-block; width: .7em; height: .7em; border-radius: 50%; background: ${C.rose}; margin-right: .6em; vertical-align: .05em; }
  `;

  function build() {
    if (hud || !document.documentElement) return !!hud;
    const style = document.createElement('style');
    style.textContent = css;
    fx = document.createElement('div'); fx.id = 'dd-fx';
    hud = document.createElement('div'); hud.id = 'dd-hud';
    labelEl = document.createElement('div'); labelEl.className = 'dd-label' + (cfg.labelBackdrop ? ' backdrop' : '');
    captionEl = document.createElement('div'); captionEl.className = 'dd-caption' + (cfg.captionStyle === 'plain' ? ' plain' : '');
    cover = document.createElement('div'); cover.className = 'dd-cover';
    hud.append(labelEl, captionEl, cover);
    document.documentElement.append(style, fx, hud);
    if (cfg.badge) badgeEl = pill(cfg.badge, cfg.badgeTone === 'after' ? C.cyan : C.amber, 'top', 'right');
    if (cfg.layoutShift && !cfg.bigCounter) clsEl = pill('LIVE CLS 0.000', cfg.badgeTone === 'after' ? C.cyan : C.amber, 'top', 'left');
    if (cfg.layoutShift && cfg.bigCounter) {
      bigEl = document.createElement('div');
      bigEl.className = 'dd-big';
      bigEl.innerHTML = `<div class="v ${cfg.badgeTone === 'after' ? 'after' : ''}">0.000</div><div class="k">LAYOUT SHIFT</div><div class="live">LIVE \u00b7 THIS SCREEN</div>`;
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

  // While a label shows, --dd-label-bottom on <html> holds its bottom edge in px,
  // so a scene can keep its content clear of it (the terminal does).
  function setLabel(text) {
    state.label = text;
    if (!build()) return;
    const root = document.documentElement.style;
    if (!text) { labelEl.classList.remove('on'); root.removeProperty('--dd-label-bottom'); return; }
    if (labelEl.dataset.text === text && labelEl.classList.contains('on')) return;
    labelEl.classList.remove('on');
    labelEl.dataset.text = text;
    labelEl.innerHTML = markup(text);
    void labelEl.offsetWidth;
    labelEl.classList.add('on');
    root.setProperty('--dd-label-bottom', `${labelEl.offsetTop + labelEl.offsetHeight}px`);
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
    // Measure the page as laid out, without the zoom it has now, so one zoom can follow another.
    const was = body.style.transform, wasFx = fx.style.transform;
    body.style.transition = 'none'; fx.style.transition = 'none';
    body.style.transform = ''; fx.style.transform = '';
    const el = spec && typeof spec.target === 'string' ? document.querySelector(spec.target) : null;
    const raw = el ? el.getBoundingClientRect() : spec && spec.target; // or {left, top, width, height}
    const b = body.getBoundingClientRect();
    body.style.transform = was; fx.style.transform = wasFx;
    void body.offsetWidth;
    fx.style.transition = '';
    body.style.transformOrigin = '0 0';
    body.style.transition = `transform ${spec ? spec.ms : 700}ms cubic-bezier(.3,.7,.2,1)`;
    fx.style.setProperty('--zoom-ms', `${spec ? spec.ms : 700}ms`);
    if (!spec) { body.style.transform = ''; fx.style.transform = ''; return; }
    if (!raw) return;
    const vw = innerWidth, vh = innerHeight;
    // Aim at the part of the target that is on screen, not at a centre far below the fold.
    const left = Math.max(raw.left, 0), top = Math.max(raw.top, 0);
    const right = Math.min(raw.left + raw.width, vw), bottom = Math.min(raw.top + raw.height, vh);
    const r = { left, top, width: Math.max(0, right - left), height: Math.max(0, bottom - top) };
    const s = spec.scale;
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const tx = vw / 2 - s * cx, ty = vh / 2 - s * cy;
    fx.style.transform = `translate(${tx}px, ${ty}px) scale(${s})`;
    body.style.transform = `translate(${(s - 1) * b.left + tx}px, ${(s - 1) * b.top + ty}px) scale(${s})`;
  }

  // Sheets: a test run, an audit, a write-up laid over the scene. A sheet drops in from
  // the top, or grows out of an element ("from": a selector). Sending the same id again
  // updates it in place, and its new lines fade in. sheets('bundle') squares them into one
  // strapped stack, sheets('ship') sends the stack off the right edge, sheets('clear') fades it.
  // spec: {id, kind, title, lines, tone, box: [left, top, width] in % of the frame, from, tilt, size, ms,
  //        height: in % of the frame (else the content's), flat: true for no shadow,
  //        dim: true (or an opacity, 1 for none of the scene) to darken the scene behind until they ship or clear}
  function setSheet(spec, instant) {
    if (!build()) return;
    state.sheets = state.sheets || {};
    const prev = state.sheets[spec.id];
    const s = Object.assign({}, prev || {}, spec);
    state.sheets[spec.id] = s;
    if (!pile) {
      scrim = document.createElement('div'); scrim.className = 'dd-scrim'; hud.insertBefore(scrim, labelEl);
      pile = document.createElement('div'); pile.className = 'dd-pile'; hud.insertBefore(pile, labelEl);
    }
    if (s.dim) {
      if (typeof s.dim === 'number') scrim.style.background = `rgb(8 10 15 / ${s.dim})`;
      scrim.classList.add('on');
    }
    let el = [...pile.children].find((e) => e.dataset && e.dataset.sheet === spec.id);
    if (!el) {
      el = document.createElement('div');
      el.className = 'dd-sheet';
      el.dataset.sheet = spec.id;
      el.innerHTML = '<div class="k"></div><div class="t"></div><div class="ls"></div>';
      pile.appendChild(el);
    }
    el.style.setProperty('--tone', C[s.tone] || s.tone || C.cyan);
    if (s.size) el.style.setProperty('--ls', s.size);
    el.querySelector('.k').textContent = s.kind || '';
    el.querySelector('.t').textContent = s.title || '';
    const box = el.querySelector('.ls');
    const lines = s.lines || [];
    for (let i = box.children.length; i < lines.length; i++) {
      const line = document.createElement('div');
      line.className = 'l' + (prev && !instant ? ' in' : '');
      line.textContent = lines[i];
      box.appendChild(line);
    }
    if (s.flat) el.style.boxShadow = 'none';
    const place = () => {
      el.style.left = `${s.box[0]}%`; el.style.top = `${s.box[1]}%`; el.style.width = `${s.box[2]}%`;
      if (s.height) el.style.height = `${s.height}%`;
    };
    if (prev) { if (spec.box) place(); return; }
    place();
    const tilt = s.tilt || 0;
    if (instant) { el.style.transform = `rotate(${tilt}deg)`; return; }
    el.style.transition = 'none';
    const src = s.from && s.from !== 'top' ? document.querySelector(s.from) : null;
    if (src) {
      // Grow out of the element: start on its box, end on the sheet's own (FLIP).
      const a = src.getBoundingClientRect(), b = el.getBoundingClientRect();
      el.style.transform = `translate(${a.left - b.left}px, ${a.top - b.top}px) scale(${a.width / b.width}, ${a.height / b.height})`;
      el.style.opacity = '0.3';
    } else {
      el.style.transform = `translateY(-115vh) rotate(${tilt * 4}deg)`;
    }
    void el.offsetWidth;
    el.style.transition = '';
    el.style.transitionDuration = `${s.ms || 650}ms`;
    el.style.transform = `rotate(${tilt}deg)`;
    el.style.opacity = '1';
  }

  function sheetsDo(op, instant) {
    state.sheetsOp = op;
    if (!build() || !pile) return;
    const els = [...pile.querySelectorAll('.dd-sheet')];
    if (op === 'bundle' && els.length) {
      const avg = (k) => els.reduce((t, e) => t + parseFloat(e.style[k]), 0) / els.length;
      const left = avg('left'), top = avg('top'), width = Math.min(...els.map((e) => parseFloat(e.style.width)));
      els.forEach((e, i) => {
        e.style.transitionDuration = '600ms';
        e.style.left = `${left + i * 0.6}%`; e.style.top = `${top + i * 0.9}%`; e.style.width = `${width}%`;
        e.style.transform = `rotate(${i % 2 ? 1.2 : -1.2}deg)`;
      });
      const strapUp = () => {
        const rs = els.map((e) => e.getBoundingClientRect());
        const x0 = Math.min(...rs.map((r) => r.left)), y0 = Math.min(...rs.map((r) => r.top));
        const x1 = Math.max(...rs.map((r) => r.right)), y1 = Math.max(...rs.map((r) => r.bottom));
        const t = Math.max(6, Math.min(innerWidth, innerHeight) * 0.016);
        const cx = x0 + (x1 - x0) * 0.62, cy = y0 + (y1 - y0) * 0.45;
        const straps = [['h', { left: x0 - t * 0.5, top: cy - t / 2, width: x1 - x0 + t, height: t }],
                        ['v', { left: cx - t / 2, top: y0 - t * 0.5, width: t, height: y1 - y0 + t }]];
        for (const [cls, st] of straps) {
          const strap = document.createElement('div');
          strap.className = `dd-strap ${cls}`;
          for (const [k, v] of Object.entries(st)) strap.style[k] = `${v}px`;
          pile.appendChild(strap);
        }
        // The bow: two loops, two tails and a knot, tied where the ribbons cross.
        const bow = document.createElement('div');
        bow.className = 'dd-bow';
        Object.assign(bow.style, { left: `${cx}px`, top: `${cy}px` });
        bow.style.setProperty('--t', `${t}px`);
        bow.style.setProperty('--lw', `${t * 6}px`);
        bow.style.setProperty('--lh', `${t * 3.8}px`);
        bow.innerHTML = '<i class="tail l"></i><i class="tail r"></i><i class="loop l"></i><i class="loop r"></i><i class="knot"></i>';
        pile.appendChild(bow);
        pile.dataset.base = `${x0},${y1},${x1}`;
        pile.style.transformOrigin = `${(x0 + x1) / 2}px ${(y0 + y1) / 2}px`;
        void pile.offsetWidth;
        pile.classList.add('bundled');
        setTimeout(() => pile.classList.add('tied'), instant ? 0 : 560);
      };
      if (instant) strapUp(); else setTimeout(strapUp, 620);
    } else if (op === 'ship') {
      if (instant) { pile.classList.add('shipped'); scrim.classList.remove('on'); return; }
      if (!smoke) { smoke = document.createElement('div'); smoke.className = 'dd-smoke'; hud.insertBefore(smoke, pile); }
      const [bx0, by, bx1] = (pile.dataset.base || `${innerWidth * 0.3},${innerHeight * 0.7},${innerWidth * 0.7}`).split(',').map(Number);
      const u = Math.min(innerWidth, innerHeight) / 100;
      for (let i = 0; i < 30; i++) {
        const puff = document.createElement('div');
        puff.className = 'dd-puff';
        const size = (7 + ((i * 37) % 7)) * u;
        const x = bx0 + (bx1 - bx0) * (((i * 53) % 100) / 100);
        Object.assign(puff.style, { left: `${x - size / 2}px`, top: `${by - size * 0.3}px`, width: `${size}px`, height: `${size}px` });
        puff.style.setProperty('--dx', `${(((i * 29) % 21) - 10) * u * 1.4}px`);
        puff.style.setProperty('--dy', `${(3 + ((i * 17) % 6)) * u}px`);
        puff.style.setProperty('--grow', `${2.6 + (i % 3) * 0.5}`);
        puff.style.setProperty('--delay', `${(i % 12) * 65}ms`);
        puff.style.setProperty('--life', `${1300 + (i % 4) * 220}ms`);
        smoke.appendChild(puff);
      }
      pile.classList.add('rumble');
      setTimeout(() => {
        pile.classList.remove('rumble');
        pile.classList.add('shipped');
        scrim.classList.remove('on');
      }, 520);
    } else if (op === 'clear') {
      pile.classList.add('cleared');
      scrim.classList.remove('on');
    }
  }

  function replay() {
    if (state.sheets) for (const s of Object.values(state.sheets)) setSheet(s, true);
    if (state.sheetsOp) sheetsDo(state.sheetsOp, true);
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
    if (clsEl) clsEl.textContent = `LIVE CLS ${cls.toFixed(3)}`;
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
    sheet: setSheet,
    sheets: sheetsDo,
    shift,
    clearShifts,
    restore(saved) { Object.assign(state, saved); replay(); if (saved.zoom) setTimeout(() => setZoom(saved.zoom), 50); },
  };
})();
