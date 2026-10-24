"""Terminal scenes: replay a real recorded Claude Code run.

    {"type": "terminal", "take": "takes/after-action-run.jsonl",
     "prompt": "UAT came back bad on the product list. What went wrong?",
     "beats": [{"say": "...", "do": [{"reveal": "tools"}]}, {"say": "...", "do": [{"reveal": "final"}]}]}

The take is the output of `claude -p "<prompt>" --output-format stream-json --verbose`,
saved as is. Nothing is typed by hand. The working folder from the run's
first line is shown as ~/<folder name>, so local paths never reach the video;
add more {"redact": [["pattern", "replacement"]]} pairs if needed.

Actions: reveal (a number, "tools" for everything before the final answer,
"final" for the rest, or "all"), every (ms between items), scroll, and the
common wait, zoom, unzoom and label.
"""

import asyncio
import html
import json
import re
from pathlib import Path

from docdocs.recorder import SceneContext, Take

CSS = """
.term { --bar: calc(var(--u) * 5.4); position: absolute; inset: calc(var(--u) * 4); background: #0B0E14; border: 1px solid #1f2633;
  border-radius: 14px; box-shadow: 0 20px 60px rgb(0 0 0 / .5); display: flex; flex-direction: column; overflow: hidden; }
.bar { display: flex; align-items: center; gap: calc(var(--u) * 1.2); height: var(--bar); box-sizing: border-box; padding: 0 calc(var(--u) * 2);
  flex: none; background: var(--bg-elevated); border-bottom: 1px solid #1f2633; font-family: var(--mono); font-size: calc(var(--u) * 2);
  color: var(--text-muted); }
.dot { width: calc(var(--u) * 1.4); height: calc(var(--u) * 1.4); border-radius: 50%; background: #2a3140; }
.scroll { flex: 1; overflow: hidden; padding: calc(var(--u) * 2.4) calc(var(--u) * 3) 30vh; font-family: var(--mono);
  font-size: calc(var(--u) * 2.3); line-height: 1.55;
  /* While a HUD label shows, start the scroll area below it, so no line runs under the label. */
  margin-top: max(0px, calc(var(--dd-label-bottom, 0px) + var(--u) * 1.2 - var(--u) * 4 - var(--bar)));
  transition: margin-top 360ms cubic-bezier(.2,.7,.2,1); }
.item { display: none; margin: 0 0 calc(var(--u) * 1.4); white-space: pre-wrap; word-break: break-word; }
.item.shown { display: block; animation: enter 300ms ease-out; }
.prompt { color: var(--text-primary); } .prompt::before { content: '> '; color: var(--cyan); }
.text { color: var(--text-primary); font-family: var(--body); font-size: calc(var(--u) * 2.6); }
.tool { color: var(--text-primary); } .tool b { color: var(--green); font-weight: 700; }
.result { color: var(--text-muted); padding-left: calc(var(--u) * 3); border-left: 2px solid #1f2633; }
.result.error { color: var(--rose); }
.final { background: var(--bg-surface); border-left: 3px solid var(--amber); padding: calc(var(--u) * 1.2) calc(var(--u) * 2.4);
  color: var(--text-primary); font-family: var(--body); font-size: calc(var(--u) * 2.8); line-height: 1.5; margin: 0; }
.final + .final { margin-top: 0; }
.text b, .final b { font-weight: 600; }
.text code, .final code { font-family: var(--mono); font-size: .86em; color: var(--cyan); background: rgb(255 255 255 / .06);
  padding: 0 .2em; border-radius: 4px; }
.final .h { display: block; font-family: var(--mono); font-weight: 700; color: var(--amber); letter-spacing: .1em; font-size: calc(var(--u) * 2.3); }
"""


def _summary(name: str, data: dict) -> str:
    for key in ("command", "file_path", "pattern", "url", "query", "description"):
        if key in data:
            return str(data[key]).splitlines()[0][:110]
    return json.dumps(data)[:110]


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    return str(content)


def parse(path: Path, redact: list[list[str]]) -> tuple[list[tuple[str, str]], str]:
    """Return (kind, html) items in order, and the folder label for the title bar."""
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    cwd = next((e.get("cwd") for e in events if e.get("type") == "system" and e.get("cwd")), None)
    folder = "~/" + re.split(r"[\\/]", cwd.rstrip("\\/"))[-1] if cwd else "~"
    rules = [(re.escape(cwd), folder)] if cwd else []
    rules += [(re.escape(cwd.replace("\\", "/")), folder)] if cwd else []
    rules += [(p, r) for p, r in redact]

    def clean(text: str) -> str:
        for pattern, repl in rules:
            text = re.sub(pattern, repl, text)
        return text

    items: list[tuple[str, str]] = []
    for e in events:
        kind = e.get("type")
        if kind == "assistant":
            for c in e["message"].get("content", []):
                if c.get("type") == "text" and c.get("text", "").strip():
                    items.append(("text", _inline(clean(c["text"].strip()))))
                elif c.get("type") == "tool_use":
                    items.append(("tool", f"● <b>{html.escape(c['name'])}</b>({html.escape(clean(_summary(c['name'], c.get('input', {}))))})"))
        elif kind == "user":
            for c in e["message"].get("content", []):
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    lines = clean(_result_text(c.get("content"))).splitlines()
                    shown = "\n".join(lines[:3])
                    more = f"\n… +{len(lines) - 3} lines" if len(lines) > 3 else ""
                    css = "result error" if c.get("is_error") else "result"
                    items.append((css, html.escape(shown + more)))
        elif kind == "result" and e.get("result"):
            # The final answer replaces the last text block if they are the same.
            if items and items[-1][0] == "text":
                items.pop()
            for block in re.split(r"\n\s*\n", clean(e["result"].strip())):
                items.append(("final", _final_block(block)))
    return items, folder


def _inline(text: str) -> str:
    """Escape text, then show Markdown `code` and **bold** as such instead of as raw marks."""
    out = html.escape(text)
    out = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", out)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)


def _final_block(block: str) -> str:
    lines = block.strip().splitlines()
    out = []
    for line in lines:
        bare = line.strip().strip("#*_ ").strip()
        if bare and bare.upper() == bare and re.search(r"[A-Z]{3}", bare) and len(bare) < 60:
            out.append(f"<span class='h'>{html.escape(bare)}</span>")
        else:
            out.append(_inline(line))
    return "\n".join(out)


async def record(ctx: SceneContext) -> Take:
    raw = ctx.scene.raw
    items, folder = parse(ctx.storyboard.resolve(raw["take"]), raw.get("redact", []))
    prompt = raw.get("prompt")
    if prompt:
        items.insert(0, ("prompt", html.escape(prompt)))
    final_at = next((i for i, (k, _) in enumerate(items) if k == "final"), len(items))
    body = (
        "<div class='stage' style='padding:0'><div class='term'>"
        f"<div class='bar'><span class='dot'></span><span class='dot'></span><span class='dot'></span>"
        f"<span>claude — {html.escape(folder)}</span></div>"
        "<div class='scroll' id='scroll'>"
        + "".join(f"<div class='item {k}'>{h}</div>" for k, h in items)
        + "</div></div></div>"
    )
    await ctx.prepare(labelBackdrop=True)
    await ctx.show_html(ctx.brand.page(body, title="terminal", head=f"<style>{CSS}</style>"))
    shown = 0
    if prompt:
        await ctx.page.evaluate("document.querySelector('.item').classList.add('shown')")
        shown = 1
    await ctx.begin()

    async def reveal_to(target: int, every_ms: float) -> None:
        nonlocal shown
        while shown < min(target, len(items)):
            await ctx.page.evaluate(
                """i => { const el = document.querySelectorAll('.item')[i]; el.classList.add('shown');
                         const s = document.getElementById('scroll');
                         const over = el.offsetTop + el.offsetHeight - s.clientHeight * 0.7;
                         if (over > s.scrollTop) s.scrollTo({top: over, behavior: 'smooth'}); }""",
                shown,
            )
            shown += 1
            await asyncio.sleep(every_ms / 1000)

    async def act(action: dict) -> None:
        (name, value), *rest = action.items()
        every = float(action.get("every", 700 if value == "final" else 250))
        if name == "reveal":
            if value == "tools":
                await reveal_to(final_at, every)
            elif value in ("final", "all"):
                await reveal_to(len(items), every)
            else:
                await reveal_to(shown + int(value), every)
        elif name == "scroll":
            await ctx.page.evaluate("y => document.getElementById('scroll').scrollBy({top: y, behavior: 'smooth'})", value)
            await asyncio.sleep(0.9)
        else:
            raise ValueError(f"{ctx.scene.label}: unknown terminal action {name!r}")

    await ctx.play(act)
    return await ctx.end()
