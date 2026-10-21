"""Card scenes: a title, a block of text, a before-and-after number, or a credit.

    {"type": "card", "template": "title",
     "fields": {"kicker": "Own It · Episode 1", "title": "The page that jumped"}}

Templates come from the brand folder. The metric template takes its numbers
from measurements.json (written by `docdocs measure`), never from the
storyboard, so the card shows what was measured.
"""

import html

from docdocs.recorder import SceneContext, Take, fill

METRICS = {
    "cls": {"label": "Cumulative Layout Shift", "digits": 3, "unit": ""},
    "lcp": {"label": "Largest Contentful Paint", "digits": 1, "unit": " s", "scale": 0.001},
}


async def record(ctx: SceneContext) -> Take:
    raw = ctx.scene.raw
    name = raw.get("template", "title")
    fields = {"kicker": "", "title": "", "subtitle": "", "body": "", "mark": ctx.brand.meta.get("mark", "")}
    fields.update(raw.get("fields", {}))
    if name == "metric":
        fields.update(metric_fields(ctx, raw))
    if name == "credit":
        lines = fields.pop("lines", [])
        fields["lines_html"] = "".join(
            f"<p class='{'link' if line.startswith(('http', 'github.com', 'devofcodes.com')) else ''}'>{html.escape(line)}</p>"
            for line in lines
        )
    body = fill(ctx.brand.template(name), fields)
    await ctx.show_html(ctx.brand.page(body, title=ctx.storyboard.title))
    await ctx.capture.start()

    async def no_actions(action: dict) -> None:
        raise ValueError(f"{ctx.scene.label}: card scenes take no actions, got {action}")

    await ctx.play(no_actions)
    return ctx.take(await ctx.capture.stop())


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
