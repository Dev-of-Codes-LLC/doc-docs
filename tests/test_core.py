"""Tests that need no browser, no voice and no network. Run: python -m unittest discover tests"""

import json
import tempfile
import unittest
from pathlib import Path

from docdocs.hosts import HostNotAllowed, check_url
from docdocs.mux import _srt_time
from docdocs.scenes.code import render
from docdocs.scenes.terminal import _final_block, _inline, parse
from docdocs.storyboard import StoryboardError, load

FIXTURES = Path(__file__).parent / "fixtures"


class Hosts(unittest.TestCase):
    def test_local_hosts_pass(self):
        for url in ("http://localhost:4173/products", "http://127.0.0.1:8080", "http://app.localhost:3000/"):
            check_url(url)

    def test_other_hosts_are_refused(self):
        for url in ("https://example.com/", "http://staging.acme.example/", "http://localhost.evil.example/"):
            with self.assertRaises(HostNotAllowed):
                check_url(url)

    def test_files_only_under_the_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            check_url((root / "page.html").as_uri(), root)
            with self.assertRaises(HostNotAllowed):
                check_url((root.parent / "other.html").as_uri(), root)

    def test_other_schemes_are_refused(self):
        with self.assertRaises(HostNotAllowed):
            check_url("ftp://localhost/file")


class Storyboards(unittest.TestCase):
    def write(self, data: dict) -> Path:
        tmp = Path(tempfile.mkdtemp())
        path = tmp / "storyboard.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_valid(self):
        sb = load(self.write({"id": "x", "title": "X", "formats": ["16:9", "9:16"],
                              "scenes": [{"type": "card", "beats": [{"say": "Hi."}]}]}))
        self.assertEqual([f.slug for f in sb.formats], ["16x9", "9x16"])
        self.assertEqual(sb.formats[0].width, 1920)
        self.assertEqual(sb.formats[1].height, 1920)
        self.assertEqual(sb.scenes[0].beats[0].say, "Hi.")

    def test_problems_are_listed_together(self):
        with self.assertRaises(StoryboardError) as e:
            load(self.write({"id": "x", "formats": ["4:3"],
                             "scenes": [{"type": "video"}, {"type": "browser", "system": "nope"}]}))
        message = str(e.exception)
        for part in ("missing 'title'", "unknown format '4:3'", "scene 1: type", "scene 2: system 'nope'"):
            self.assertIn(part, message)

    def test_scene_without_beats_still_shows(self):
        sb = load(self.write({"id": "x", "title": "X", "scenes": [{"type": "card", "hold": 1500}]}))
        self.assertEqual(sb.scenes[0].beats[0].hold_ms, 1500)


class Terminal(unittest.TestCase):
    def test_parse_hides_the_working_folder(self):
        items, folder = parse(FIXTURES / "sample-run.jsonl", [])
        self.assertEqual(folder, "~/own-it-demo")
        text = " ".join(h for _, h in items)
        self.assertNotIn("someone", text)
        self.assertIn("~/own-it-demo", text)

    def test_parse_orders_tools_then_final(self):
        items, _ = parse(FIXTURES / "sample-run.jsonl", [])
        kinds = [k for k, _ in items]
        self.assertIn("tool", kinds)
        self.assertIn("result", kinds)
        first_final = kinds.index("final")
        self.assertTrue(all(k == "final" for k in kinds[first_final:]))
        self.assertEqual(kinds.count("final"), 4)  # four headed blocks

    def test_extra_redactions(self):
        items, _ = parse(FIXTURES / "sample-run.jsonl", [["Acme Supply", "the shop"]])
        self.assertNotIn("Acme Supply", " ".join(h for _, h in items))

    def test_inline_code_and_bold(self):
        self.assertEqual(
            _inline("Code at `a89f997`: `<App>` is **wrong** & `x`"),
            "Code at <code>a89f997</code>: <code>&lt;App&gt;</code> is <b>wrong</b> &amp; <code>x</code>",
        )
        self.assertEqual(_inline("a lone ` stays"), "a lone ` stays")
        self.assertIn("<code>uat/feedback.md</code>", _final_block("- UAT notes: `uat/feedback.md`"))

    def test_text_items_render_inline_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            take = Path(tmp) / "take.jsonl"
            event = {"type": "assistant", "message": {"content": [{"type": "text", "text": "Reading `api.ts` now."}]}}
            take.write_text(json.dumps(event) + "\n", encoding="utf-8")
            items, _ = parse(take, [])
        self.assertEqual(items, [("text", "Reading <code>api.ts</code> now.")])


class Code(unittest.TestCase):
    def test_render_marks_added_and_removed_lines(self):
        diff = (
            "diff --git a/src/a.ts b/src/a.ts\nindex 1..2 100644\n--- a/src/a.ts\n+++ b/src/a.ts\n"
            "@@ -1,2 +1,2 @@\n keep\n-old <b>\n+new\n"
        )
        out = render(diff)
        self.assertIn("src/a.ts", out)
        self.assertIn("line del", out)
        self.assertIn("line add", out)
        self.assertIn("old &lt;b&gt;", out)  # escaped
        self.assertIn("<span class='n'>2</span><span class='s'>+</span>", out)


class Captions(unittest.TestCase):
    def test_srt_time(self):
        self.assertEqual(_srt_time(0), "00:00:00,000")
        self.assertEqual(_srt_time(3725.4567), "01:02:05,457")


if __name__ == "__main__":
    unittest.main()


class Timing(unittest.TestCase):
    def test_caption_chunks_follow_the_words(self):
        import wave as _wave
        from docdocs.captions import timings

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clip.wav"
            with _wave.open(str(path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(22050)
                # 0.2 s silence, 1.6 s of signal, 0.2 s silence
                quiet, loud = b"\x00\x00" * 4410, (b"\x00\x40" + b"\x00\xc0") * 17640
                wf.writeframes(quiet + loud + quiet)
            chunks = timings("The grey blocks are too small, so the cards shove everything down.", path)
        words = [w for c in chunks for w in c["words"]]
        self.assertEqual(" ".join(words), "The grey blocks are too small, so the cards shove everything down.")
        times = [t for c in chunks for t in c["times"]]
        self.assertGreaterEqual(times[0][0], 190)  # speech starts after the leading silence
        self.assertLessEqual(times[-1][1], 1810)
        self.assertTrue(all(a < b for a, b in times))
        self.assertTrue(all(len(c["words"]) <= 6 for c in chunks))
        self.assertEqual(chunks[0]["words"][-1], "small,")  # breaks after punctuation

    def test_speed_maps_take_time_to_video_time(self):
        from docdocs.mux import _out_time, _rate
        from docdocs.recorder import Take

        take = Take(duration=10, segments=[(2.0, 6.0, 2.0)])
        self.assertEqual(_rate(take, 1.0), 1.0)
        self.assertEqual(_rate(take, 3.0), 2.0)
        self.assertEqual(_out_time(take, 2.0), 2.0)
        self.assertEqual(_out_time(take, 6.0), 4.0)  # four seconds at 2x take two
        self.assertEqual(_out_time(take, 8.0), 6.0)


class Series(unittest.TestCase):
    def test_intro_after_the_hook_and_placeholders(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "series.json").write_text(json.dumps({
            "introAfterFirst": True,
            "intro": [{"type": "card", "template": "sting", "fields": {"subtitle": "Episode {episode}"}}],
            "outro": [{"type": "card", "template": "outro", "fields": {"next": "Next: {next}"}}],
        }), encoding="utf-8")
        path = tmp / "ep" / "storyboard.json"
        path.parent.mkdir()
        path.write_text(json.dumps({"id": "x", "title": "X", "episode": 3, "next": "the cache", "series": "../series.json",
                                    "scenes": [{"type": "card", "template": "hook"}, {"type": "card"}]}), encoding="utf-8")
        sb = load(path)
        self.assertEqual([s.raw.get("template") for s in sb.scenes], ["hook", "sting", None, "outro"])
        self.assertEqual(sb.scenes[1].raw["fields"]["subtitle"], "Episode 3")
        self.assertEqual(sb.scenes[3].raw["fields"]["next"], "Next: the cache")
