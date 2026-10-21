"""Code scenes: a real git diff, rendered in the brand.

    {"type": "code", "repo": "../..", "diff": "before..after",
     "files": ["src/components/ProductSkeleton.tsx"], "title": "Fix 1: size the skeleton",
     "beats": [{"say": "...", "do": [{"file": 2}]}]}

Actions: file (scroll to the nth file, 1-based), scroll (pixels), wait (ms).
"""

import asyncio
import html
import re
import subprocess

from docdocs.recorder import SceneContext, Take

CSS = """
.diff { position: absolute; inset: 0; overflow: hidden; padding: calc(var(--u) * 5) calc(var(--u) * 5) 40vh; }
.diff-head { font-family: var(--mono); font-size: calc(var(--u) * 2.2); color: var(--cyan); letter-spacing: .12em;
  text-transform: uppercase; margin: 0 0 calc(var(--u) * 1); }
.diff-title { font-family: var(--display); font-weight: 800; font-size: calc(var(--u) * 5); margin: 0 0 calc(var(--u) * 4); }
.file { background: var(--bg-surface); border: 1px solid #1f2633; border-radius: 12px; margin: 0 0 calc(var(--u) * 4); overflow: hidden; }
.file-name { font-family: var(--mono); font-size: calc(var(--u) * 2.2); color: var(--text-secondary);
  padding: calc(var(--u) * 1.6) calc(var(--u) * 2.4); background: var(--bg-elevated); border-bottom: 1px solid #1f2633; }
.hunk { font-family: var(--mono); font-size: calc(var(--u) * 2.1); color: var(--text-muted); padding: calc(var(--u) * .8) calc(var(--u) * 2.4); }
.line { display: grid; grid-template-columns: calc(var(--u) * 6) calc(var(--u) * 3) 1fr; font-family: var(--mono);
  font-size: calc(var(--u) * 2.3); line-height: 1.55; white-space: pre-wrap; word-break: break-word; }
.line .n { color: var(--text-muted); text-align: right; padding-right: calc(var(--u) * 1.4); }
.line .s { color: var(--text-muted); }
.line.add { background: rgb(0 200 255 / .10); } .line.add .s, .line.add .c { color: #7fe3ff; }
.line.del { background: rgb(245 158 11 / .10); } .line.del .s, .line.del .c { color: #fbc66b; }
.line .c { color: var(--text-primary); }
"""


def git_diff(repo, spec: str, files: list[str]) -> str:
    cmd = ["git", "-C", str(repo), "diff", "--no-color", "-U3", spec, "--", *files]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"git diff {spec}: {result.stderr.strip()}")
    if not result.stdout.strip():
        raise RuntimeError(f"git diff {spec} -- {' '.join(files)} is empty")
    return result.stdout


def render(diff: str) -> str:
    out = []
    new_no = 0
    for line in diff.splitlines():
        if line.startswith("diff --git"):
            if out:
                out.append("</div>")
            name = line.split(" b/", 1)[-1]
            out.append(f"<div class='file'><div class='file-name'>{html.escape(name)}</div>")
        elif line.startswith(("index ", "--- ", "+++ ", "new file", "deleted file", "similarity", "rename ")):
            continue
        elif line.startswith("@@"):
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", line)
            new_no = int(m.group(1)) if m else 0
            out.append(f"<div class='hunk'>{html.escape(line.split('@@')[-1].strip() or '…')}</div>")
        elif line.startswith("+"):
            out.append(f"<div class='line add'><span class='n'>{new_no}</span><span class='s'>+</span><span class='c'>{html.escape(line[1:])}</span></div>")
            new_no += 1
        elif line.startswith("-"):
            out.append(f"<div class='line del'><span class='n'></span><span class='s'>-</span><span class='c'>{html.escape(line[1:])}</span></div>")
        elif line.startswith("\\"):
            continue
        else:
            out.append(f"<div class='line'><span class='n'>{new_no}</span><span class='s'></span><span class='c'>{html.escape(line[1:])}</span></div>")
            new_no += 1
    if out:
        out.append("</div>")
    return "".join(out)


async def record(ctx: SceneContext) -> Take:
    raw = ctx.scene.raw
    repo = ctx.storyboard.resolve(raw.get("repo", "."))
    diff = git_diff(repo, raw["diff"], raw.get("files", []))
    body = (
        "<div class='diff' id='diff'>"
        f"<p class='diff-head'>{html.escape(raw.get('kicker', 'git diff ' + raw['diff']))}</p>"
        f"<h1 class='diff-title'>{html.escape(raw.get('title', ''))}</h1>"
        f"{render(diff)}</div>"
    )
    await ctx.show_html(ctx.brand.page(body, title=raw.get("title", ""), head=f"<style>{CSS}</style>"))
    await ctx.capture.start()

    async def act(action: dict) -> None:
        (name, value), *rest = action.items()
        if name == "file":
            await ctx.page.evaluate(
                """n => { const el = document.querySelectorAll('.file')[n - 1]; const box = document.getElementById('diff');
                         if (el) box.scrollTo({top: el.offsetTop - 24, behavior: 'smooth'}); }""",
                int(value),
            )
            await asyncio.sleep(0.9)
        elif name == "scroll":
            await ctx.page.evaluate("y => document.getElementById('diff').scrollBy({top: y, behavior: 'smooth'})", value)
            await asyncio.sleep(0.9)
        elif name == "wait":
            await asyncio.sleep(float(value) / 1000)
        else:
            raise ValueError(f"{ctx.scene.label}: unknown code action {name!r}")

    await ctx.play(act)
    return ctx.take(await ctx.capture.stop())
