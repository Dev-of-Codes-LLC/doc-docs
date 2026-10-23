"""Explain scenes: an animated diagram on one continuous canvas.

Elements are placed in percent of the frame (x and y from 0 to 100). Give
"at" as a list, or per format: {"16:9": [...], "9:16": [...]}. Elements
start hidden unless "visible": true; beats show them, move them, light them
up and count them, so the picture builds and changes without cutting.

    {"type": "explain",
     "elements": [
       {"id": "frame", "kind": "box", "at": [30, 15, 40, 72], "style": "solid", "tone": "muted"},
       {"id": "img", "kind": "box", "at": [34, 24, 32, 0], "style": "dashed", "tone": "amber", "label": "image"},
       {"id": "cls", "kind": "counter", "at": [80, 45], "label": "CLS", "digits": 3, "tone": "amber"}
     ],
     "beats": [
       {"say": "...", "label": "the page *moves*", "do": [{"show": ["frame", "img"]}, {"set": {"id": "img", "at": [34, 24, 32, 20]}}, {"count": {"id": "cls", "to": 0.25}}]}
     ]}

Kinds: text, box, dot, dots (a scattered field), axes, line (from/to an id or
a point), pill (parts that light up), counter, check.
Actions: show, hide, set, light, count, pulse, and the common wait, zoom,
unzoom and label.
"""

import html
import json
import random
import re

from docdocs.recorder import SceneContext, Take

TONES = {"cyan": "#00C8FF", "amber": "#F59E0B", "rose": "#F43F5E", "green": "#10B981",
         "muted": "#5C6573", "white": "#E8EAF0", "dim": "#2A3140"}

CSS = """
.ex { position: absolute; inset: 0; overflow: hidden; }
.el { position: absolute; opacity: 0; transition: opacity 380ms ease-out, left var(--ms, 700ms) cubic-bezier(.3,.7,.2,1),
  top var(--ms, 700ms) cubic-bezier(.3,.7,.2,1), width var(--ms, 700ms) cubic-bezier(.3,.7,.2,1),
  height var(--ms, 700ms) cubic-bezier(.3,.7,.2,1), transform 380ms cubic-bezier(.3,.7,.2,1); }
.el.on { opacity: 1; }
.el.pulse { transform: scale(1.06); }
.text { transform: translate(-50%, -50%); white-space: pre-wrap; text-align: center; color: var(--text-primary);
  font-family: var(--body); line-height: 1.2; letter-spacing: -0.01em; max-width: 80vw; }
.text.left { transform: translate(0, -50%); text-align: left; }
.text.mono { font-family: var(--mono); letter-spacing: .04em; }
.text.display { font-family: var(--display); font-weight: 800; }
.text em { font-style: normal; color: var(--amber); } .text em.cyan { color: var(--cyan); }
.box { border-radius: calc(var(--u) * 1.2); box-sizing: border-box; }
.box .tag { position: absolute; left: 0; top: calc(var(--u) * -3.2); font-family: var(--mono); font-size: calc(var(--u) * 1.9);
  letter-spacing: .08em; color: var(--tone); white-space: nowrap; }
.dot { width: var(--s); height: var(--s); margin: calc(var(--s) / -2) 0 0 calc(var(--s) / -2); border-radius: 50%;
  background: radial-gradient(circle, #fff6 0 18%, var(--tone) 40%, transparent 72%);
  box-shadow: 0 0 calc(var(--s) * 1.2) calc(var(--s) * .25) color-mix(in srgb, var(--tone) 45%, transparent); }
.axes { border-left: 1.5px solid #c9ced8; border-bottom: 1.5px solid #c9ced8; }
.axes .ax { position: absolute; font-family: var(--body); color: #c9ced8; font-size: calc(var(--u) * 2.2); white-space: nowrap; }
.axes .ax.x { right: 0; bottom: calc(var(--u) * -4); }
.axes .ax.y { left: calc(var(--u) * -3.4); bottom: 0; transform-origin: 0 100%; transform: rotate(-90deg) translateY(0); }
.pill { transform: translate(-50%, -50%); display: flex; gap: calc(var(--u) * 1.4); padding: calc(var(--u) * 1) calc(var(--u) * 2.2);
  background: #111722; border: 1px solid #263044; border-radius: calc(var(--u) * 1.2); font-family: var(--mono);
  font-size: calc(var(--u) * 2.6); color: var(--text-muted); }
.pill .part { transition: color 250ms; } .pill .part.lit { color: var(--cyan); } .pill .sep { color: #33405a; }
.counter { transform: translate(-50%, -50%); text-align: center; }
.counter .v { font-family: var(--mono); font-weight: 700; font-size: calc(var(--u) * 8); color: var(--tone); line-height: 1; }
.counter .k { font-family: var(--mono); font-size: calc(var(--u) * 2.2); letter-spacing: .14em; color: var(--text-secondary); margin-top: calc(var(--u) * 1.2); }
.check { transform: translate(-50%, -50%); text-align: center; }
.check svg { width: calc(var(--u) * 14); height: calc(var(--u) * 14); }
.check circle { fill: none; stroke: var(--tone); stroke-width: 3; opacity: .8; }
.check path { fill: none; stroke: var(--amber); stroke-width: 6; stroke-linecap: round; stroke-linejoin: round;
  stroke-dasharray: 60; stroke-dashoffset: 60; transition: stroke-dashoffset 600ms ease-out 200ms; }
.check.on path { stroke-dashoffset: 0; }
.check .t { margin-top: calc(var(--u) * 2); display: inline-block; padding: calc(var(--u) * 1) calc(var(--u) * 2.4);
  border: 1px solid #2c3a52; border-radius: calc(var(--u) * 1); background: #0f1520; font-family: var(--body);
  font-size: calc(var(--u) * 3.6); color: var(--text-primary); }
svg.lines { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
svg.lines line { opacity: 0; transition: opacity 300ms, stroke-dashoffset 600ms ease-out; }
svg.lines line.on { opacity: 1; stroke-dashoffset: 0 !important; }
"""

RUNTIME = """
const els = Object.fromEntries([...document.querySelectorAll('[data-id]')].map(e => [e.dataset.id, e]));
const groups = {};
for (const e of Object.values(els)) { const g = e.dataset.group; if (g) (groups[g] = groups[g] || []).push(e); }
const lines = [...document.querySelectorAll('svg.lines line')];
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const pick = (ids) => [].concat(ids).flatMap(id => groups[id] || (els[id] ? [els[id]] : lines.filter(l => l.dataset.id === id)));
function center(ref) {
  if (Array.isArray(ref)) return [ref[0] / 100 * innerWidth, ref[1] / 100 * innerHeight];
  const e = els[ref]; if (!e) return [0, 0];
  const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2];
}
function drawLines() {
  for (const l of lines) {
    const [x1, y1] = center(JSON.parse(l.dataset.from)), [x2, y2] = center(JSON.parse(l.dataset.to));
    l.setAttribute('x1', x1); l.setAttribute('y1', y1); l.setAttribute('x2', x2); l.setAttribute('y2', y2);
    if (!l.dataset.dashed && !l.dataset.len) { const len = Math.hypot(x2 - x1, y2 - y1); l.style.strokeDasharray = len; l.style.strokeDashoffset = len; l.dataset.len = len; }
  }
  requestAnimationFrame(drawLines);
}
drawLines();
function place(e, at) {
  e.style.left = at[0] + '%'; e.style.top = at[1] + '%';
  if (at.length > 2) { e.style.width = at[2] + '%'; e.style.height = at[3] + '%'; }
}
window.dd = {
  async show(spec) {
    const ids = spec.ids || spec; const stagger = spec.stagger ?? 90;
    for (const e of pick(ids)) { e.classList.add('on'); if (stagger) await sleep(stagger); }
    await sleep(300);
  },
  async hide(ids) { for (const e of pick(ids)) e.classList.remove('on'); await sleep(380); },
  async set(spec) {
    const ms = spec.ms ?? 700;
    for (const e of pick(spec.id)) {
      e.style.setProperty('--ms', ms + 'ms');
      if (spec.at) place(e, spec.at);
      if (spec.tone) e.style.setProperty('--tone', spec.tone);
      if (spec.html !== undefined) (e.querySelector('.t, .v') || e).innerHTML = spec.html;
    }
    await sleep(ms);
  },
  async light(spec) {
    const parts = els[spec.id].querySelectorAll('.part');
    parts.forEach((p, i) => p.classList.toggle('lit', spec.part === 'all' || (spec.upTo ? i < spec.part : i === spec.part - 1)));
    await sleep(250);
  },
  async count(spec) {
    const e = els[spec.id], v = e.querySelector('.v'), digits = +e.dataset.digits;
    const from = parseFloat(v.textContent) || 0, to = spec.to, ms = spec.ms ?? 900, t0 = performance.now();
    await new Promise(done => { const step = (now) => { const k = Math.min(1, (now - t0) / ms), ease = 1 - Math.pow(1 - k, 3);
      v.textContent = (from + (to - from) * ease).toFixed(digits); k < 1 ? requestAnimationFrame(step) : done(); }; requestAnimationFrame(step); });
  },
  async pulse(ids) { const list = pick(ids); list.forEach(e => e.classList.add('pulse')); await sleep(260); list.forEach(e => e.classList.remove('pulse')); await sleep(200); },
};
"""


def _at(element: dict, fmt_name: str):
    at = element.get("at")
    if isinstance(at, dict):
        at = at.get(fmt_name) or next(iter(at.values()))
    return at


def _markup(text: str) -> str:
    t = html.escape(text)
    return re.sub(r"_(.+?)_", r"<em class='cyan'>\1</em>", re.sub(r"\*(.+?)\*", r"<em>\1</em>", t))


def _style(at, tone: str, extra: str = "") -> str:
    pos = f"left:{at[0]}%;top:{at[1]}%;" + (f"width:{at[2]}%;height:{at[3]}%;" if len(at) > 2 else "")
    return f"{pos}--tone:{TONES.get(tone, tone)};{extra}"


def render(elements: list[dict], fmt_name: str) -> str:
    out, svg = [], []
    for el in elements:
        kind, eid = el.get("kind"), el.get("id", "")
        on = " on" if el.get("visible") else ""
        tone = el.get("tone", "white")
        at = _at(el, fmt_name)
        if kind == "line":
            color = TONES.get(el.get("tone", "cyan"), el.get("tone", "cyan"))
            dash = "stroke-dasharray:6 6;" if el.get("dashed") else ""
            svg.append(
                f"<line data-id='{eid}' class='{on.strip()}' data-from='{json.dumps(el['from'])}' data-to='{json.dumps(el['to'])}'"
                f"{' data-dashed=1' if el.get('dashed') else ''} stroke='{color}' stroke-width='{el.get('width', 2)}' style='{dash}'/>"
            )
        elif kind == "text":
            cls = " ".join(c for c in (el.get("align") == "left" and "left", el.get("font")) if c)
            size = el.get("size", 4.4)
            out.append(f"<div data-id='{eid}' class='el text {cls}{on}' style='{_style(at, tone)}font-size:calc(var(--u)*{size})'>{_markup(el.get('text', ''))}</div>")
        elif kind == "box":
            style = el.get("style", "dashed")
            color = TONES.get(tone, tone)
            if style == "fill":
                look = f"background:{color};opacity:1;"
            elif style == "solid":
                look = f"border:2px solid {color};background:color-mix(in srgb, {color} 8%, transparent);"
            else:
                look = f"border:2px dashed {color};background:color-mix(in srgb, {color} 7%, transparent);"
            tag = f"<span class='tag'>{html.escape(el['label'])}</span>" if el.get("label") else ""
            out.append(f"<div data-id='{eid}' class='el box{on}' style='{_style(at, tone, look)}'>{tag}</div>")
        elif kind == "dot":
            out.append(f"<div data-id='{eid}' class='el dot{on}' style='{_style(at, tone)}--s:calc(var(--u)*{el.get('size', 1.8)})'></div>")
        elif kind == "dots":
            rng = random.Random(el.get("seed", 1))
            x, y, w, h = at
            for n in range(int(el.get("count", 24))):
                px, py = x + rng.random() * w, y + rng.random() * h
                out.append(f"<div data-id='{eid}.{n}' data-group='{eid}' class='el dot{on}' style='{_style([round(px, 2), round(py, 2)], tone)}--s:calc(var(--u)*{el.get('size', 1.4)})'></div>")
        elif kind == "axes":
            out.append(
                f"<div data-id='{eid}' class='el axes{on}' style='{_style(at, tone)}'>"
                f"<span class='ax x'>{html.escape(el.get('x', ''))}</span><span class='ax y'>{html.escape(el.get('y', ''))}</span></div>"
            )
        elif kind == "pill":
            parts = "<span class='sep'>|</span>".join(f"<span class='part'>{html.escape(p)}</span>" for p in el.get("parts", []))
            out.append(f"<div data-id='{eid}' class='el pill{on}' style='{_style(at, tone)}'>{parts}</div>")
        elif kind == "counter":
            digits = int(el.get("digits", 0))
            value = f"{float(el.get('value', 0)):.{digits}f}"
            out.append(
                f"<div data-id='{eid}' data-digits='{digits}' class='el counter{on}' style='{_style(at, el.get('tone', 'amber'))}'>"
                f"<div class='v'>{value}</div><div class='k'>{html.escape(el.get('label', ''))}</div></div>"
            )
        elif kind == "check":
            out.append(
                f"<div data-id='{eid}' class='el check{on}' style='{_style(at, el.get('tone', 'cyan'))}'>"
                "<svg viewBox='0 0 100 100'><circle cx='50' cy='50' r='44'/><path d='M30 52 L45 66 L72 36'/></svg>"
                f"<div><span class='t'>{_markup(el.get('text', ''))}</span></div></div>"
            )
        else:
            raise ValueError(f"unknown explain element kind {kind!r}")
    return f"<div class='stage ex'><svg class='lines'>{''.join(svg)}</svg>{''.join(out)}</div>"


async def record(ctx: SceneContext) -> Take:
    raw = ctx.scene.raw
    body = render(raw.get("elements", []), ctx.fmt.name) + f"<script>{RUNTIME}</script>"
    await ctx.prepare()
    await ctx.show_html(ctx.brand.page(body, title="explain", head=f"<style>{CSS}</style>"))
    await ctx.begin()

    async def act(action: dict) -> None:
        (name, value), *_ = action.items()
        if name not in ("show", "hide", "set", "light", "count", "pulse"):
            raise ValueError(f"{ctx.scene.label}: unknown explain action {name!r}")
        if name == "set" and isinstance(value, dict) and "at" in value and isinstance(value["at"], dict):
            value = {**value, "at": value["at"].get(ctx.fmt.name) or next(iter(value["at"].values()))}
        if name == "set" and isinstance(value, dict) and "text" in value:
            value = {**value, "html": _markup(value.pop("text"))}
        if name == "set" and isinstance(value, dict) and "tone" in value:
            value = {**value, "tone": TONES.get(value["tone"], value["tone"])}
        await ctx.page.evaluate("([n, v]) => window.dd[n](v)", [name, value])

    await ctx.play(act)
    return await ctx.end()
