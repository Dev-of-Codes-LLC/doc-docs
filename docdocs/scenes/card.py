"""Card scenes: a title, a block of text, a before-and-after number, or a credit.

    {"type": "card", "template": "title",
     "fields": {"kicker": "Own It · Episode 1", "title": "The page that jumped"}}

Templates come from the brand folder. The metric template takes its numbers
from measurements.json (written by `docdocs measure`), never from the
storyboard, so the card shows what was measured.

Templates for a pitch or a trailer:

- poster    the wordmark over a headline, drawn complete on its first frame
- headline  the poster's headline alone, entering
- endcard   the wordmark in the poster's place, an amber call to action and
            a link (fields cta and url)
- still     a screenshot in a frame of its tone, panning slowly: "image" is
            a path from the storyboard's folder; fields tone and pan (how far
            it travels, e.g. "-40%")
- screen    the same screenshot under a heading (title) and a subheading
            (subtitle). Zoom into the shot and the heading leaves the frame;
            zoom to a box around the shot to end on the shot alone
- slot      a dashed frame that holds the place of footage still to come,
            with a short tag

A tone is a name from the explain scene's tones (green, violet, cyan, grey...)
or a CSS colour.

Cards take one action of their own, "show": a CSS selector. Once a scene
shows anything, the template's entering elements (class "in") wait for it
instead of entering on their own, so {"show": ".cta", "at": "Discuss"} puts
the call to action on screen as the voice says it.
"""

import html
import re
import shutil

from docdocs.recorder import SceneContext, Take, fill
from docdocs.scenes.explain import TONES

METRICS = {
    "cls": {"label": "Cumulative Layout Shift", "digits": 3, "unit": ""},
    "lcp": {"label": "Largest Contentful Paint", "digits": 1, "unit": " s", "scale": 0.001},
}


def base_fields(meta: dict) -> dict:
    """Every template field, empty or from the brand, so no ${field} is ever left in a page."""
    return {"kicker": "", "title": "", "subtitle": "", "body": "", "mark": meta.get("mark", ""),
            "wordmark": meta.get("name", ""), "url": meta.get("mark", ""), "cta": "",
            "tag": "", "tone": "grey", "image": "", "pan": "0%"}


async def record(ctx: SceneContext) -> Take:
    raw = ctx.scene.raw
    name = raw.get("template", "title")
    fields = base_fields(ctx.brand.meta)
    fields.update(raw.get("fields", {}))
    fields["tone"] = TONES.get(fields["tone"], fields["tone"])
    if raw.get("image"):
        # Copied next to the page, so the scene only opens files under its own folder.
        src = ctx.storyboard.resolve(raw["image"])
        if not src.exists():
            raise FileNotFoundError(f"{ctx.scene.label}: image {src} not found")
        copy = ctx.dir / f"image{src.suffix}"
        shutil.copyfile(src, copy)
        fields["image"] = copy.as_uri()
    if name == "metric":
        fields.update(metric_fields(ctx, raw))
    if name == "credit":
        lines = fields.pop("lines", [])
        fields["lines_html"] = "".join(
            f"<p class='{'link' if line.startswith(('http', 'github.com', 'devofcodes.com')) else ''}'>{html.escape(line)}</p>"
            for line in lines
        )
    if name == "hook":
        # "How does it *know*?" builds word by word; *word* is the amber accent.
        spans = []
        for i, word in enumerate(fields.pop("text", "").split()):
            text = html.escape(word)
            if "*" in word:
                text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
            spans.append(f"<span class='w in' style='--d: {150 + i * 160}ms'>{text}</span>")
        fields["words_html"] = " ".join(spans)
    body = fill(ctx.brand.template(name), fields)
    if raw.get("stage", ctx.storyboard.stage) == "plain":
        body = body.replace('class="stage', 'class="stage plain', 1)
    if any("show" in action for beat in ctx.scene.beats for action in beat.actions):
        body = body.replace('class="stage', 'class="stage wait', 1)
    await ctx.prepare()
    await ctx.show_html(ctx.brand.page(body, title=ctx.storyboard.title))
    await ctx.begin()

    async def act(action: dict) -> None:
        (name, value), *_ = action.items()
        if name != "show":
            raise ValueError(f"{ctx.scene.label}: card scenes take only show, wait, zoom and label, got {action}")
        await ctx.page.evaluate("s => document.querySelectorAll(s).forEach(e => e.classList.add('on'))", value)

    await ctx.play(act)
    return await ctx.end()


def metric_fields(ctx: SceneContext, raw: dict) -> dict:
    metric = raw.get("metric", "cls")
    spec = METRICS.get(metric)
    if spec is None:
        raise ValueError(f"{ctx.scene.label}: unknown metric {metric!r} (use {', '.join(METRICS)})")
    m = ctx.measurements
    if not m:
        raise ValueError(f"{ctx.scene.label}: the metric card needs measurements.json. Run: docdocs measure {ctx.storyboard.path.name}")
    refs = list(m["refs"])
    before, after = raw.get("refs", refs[:2])

    def value(ref: str) -> str:
        v = m["refs"][ref][metric]["median"] * spec.get("scale", 1)
        return f"{v:.{spec['digits']}f}{spec['unit']}"

    return {
        "label": raw.get("fields", {}).get("label", spec["label"]),
        "before_value": value(before),
        "after_value": value(after),
        "before_label": before,
        "after_label": after,
        "note": f"Lighthouse {m['lighthouse']} · {m['network']} · " + (f"median of {m['runs']} runs" if m["runs"] > 1 else "1 run") + f" · {m['date']}",
    }
