# DOC Docs

DevOfCodes Docs turns a storyboard into a narrated video of a real product: the real app in a real browser, a real `git diff`, a real recorded agent run, and cards with real measurements. One JSON file in, an MP4 and SRT captions out, in 16:9 and 9:16.

Status: phase 1. The video half works end to end. Guide chapters, the agents that write them, and publishers come later (see [the roadmap](#roadmap)).

## Install

Python 3.11 or newer.

```bash
pipx install "docdocs[kokoro] @ git+https://github.com/Dev-of-Codes-LLC/doc-docs"
python -m playwright install chromium
docdocs voices install kokoro
```

The default voice is [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M): local, free, natural-sounding, and the same on Windows, Linux and macOS. Its weights are Apache-2.0. `docdocs voices install kokoro` downloads the model (about 350 MB) into your user folder. Pick a speaker with `"voice": "kokoro:am_michael"` (others: `am_fenrir`, `am_puck`, `am_echo`, `bm_george`, `af_heart` and more).

Kokoro's phonemizer and espeak-ng, like [Piper](https://github.com/OHF-Voice/piper1-gpl), are GPL-3.0. DOC Docs runs them as separate programs and never imports them, so DOC Docs itself stays MIT. Piper is still available (`"voice": "piper:<voice>"`) but sounds more robotic.

**Check the voice's licence before you publish.** Each Piper voice is trained on a dataset with its own licence, listed in its `MODEL_CARD` on [Hugging Face](https://huggingface.co/rhasspy/piper-voices). Some are non-commercial only: `en_US-ryan-*` is CC BY-NC-SA, for example. `en_US-joe-medium` is trained on a CC0 dataset (checked 2026-10-21).

ffmpeg comes with the package (`imageio-ffmpeg`); a system `ffmpeg` on `PATH` is used first if there is one. `docdocs measure` also needs Node.js 18+ for Lighthouse.

## Quick start

```bash
docdocs check examples/cards/storyboard.json
docdocs build examples/cards/storyboard.json
```

The videos land in `examples/cards/build/`. Add `--voice silent` to check timing without a voice.

## Commands

| Command | What it does |
| --- | --- |
| `docdocs check <storyboard>` | Checks the storyboard and lists its scenes. Records nothing. |
| `docdocs build <storyboard>` | Records every scene in every format, then stitches each format into one MP4 + SRT. |
| `docdocs build <storyboard> --scenes 3` | Re-records scene 3 only (1-based, comma-separated) and re-stitches. The other takes are reused. |
| `docdocs build <storyboard> --format 9:16` | One format only. |
| `docdocs build <storyboard> --only stitch` | Re-stitches from the saved takes without recording. |
| `docdocs measure <storyboard>` | Runs Lighthouse on each ref in the `measure` block and writes `measurements.json` next to the storyboard. |
| `docdocs voices install kokoro` | Downloads the Kokoro model into your user folder. `docdocs voices install <piper voice>` gets a Piper voice; `docdocs voices list` shows the Piper voices you have. |

## A storyboard

```json
{
  "id": "own-it-01-after-action",
  "title": "Own It #1: the page that jumped",
  "formats": ["16:9", "9:16"],
  "voice": "kokoro:am_michael",
  "systems": {
    "demo": { "repo": "../..", "baseUrl": "http://localhost:4173",
              "install": "npm ci", "build": "npm run build", "serve": "npm run preview" }
  },
  "measure": { "system": "demo", "page": "/products?delay=1500", "network": "slow-4g",
               "refs": ["before", "after"], "runs": 3, "lighthouse": "13.5.0" },
  "scenes": [
    { "type": "card", "template": "title", "fields": { "kicker": "Own It · 1", "title": "The page that jumped" },
      "beats": [ { "say": "UAT came back bad." } ] },
    { "type": "browser", "system": "demo", "checkout": "before", "network": "slow-4g",
      "overlay": ["layout-shift"], "badge": "before · Slow 4G",
      "beats": [ { "say": "Here is the page on a slow phone.", "do": [ { "goto": "/products" }, { "waitFor": "main[data-state=loaded]" } ] } ] },
    { "type": "card", "template": "metric", "metric": "cls", "beats": [ { "say": "Measured, not guessed." } ] }
  ]
}
```

A **beat** is one sentence of narration (`say`) plus the actions it describes (`do`). The beat lasts as long as the longer of the two, plus a short pause; `hold` (ms) sets a minimum. Paths are relative to the storyboard's folder.

A beat can also carry:

- `label`: a key phrase on screen while the beat plays, like `"everything below *jumps*"`. `*word*` is the amber accent and `_word_` the cyan one. One phrase per idea carries the meaning even with the sound off.
- `speed`: play the beat faster, for example `2` while a throttled page loads. The video shows a "2× SPEED" badge for that stretch, and the narration still plays at normal speed.

Any action can wait for its moment with `at`: `{"show": "img", "at": "picture"}` fires when the voice reaches "picture" (the first match after the previous anchor in the beat), and `"at": 1200` fires 1.2 s into the beat. Anchor the visual to the word that names it, and the picture lands when it is said.

Every scene type also understands these actions: `wait` (ms), `zoom` (a CSS selector, with `scale` and `ms`) to push in on what is moving, `unzoom`, and `label`.

### Storyboard settings

| Key | What it does |
| --- | --- |
| `voiceSpeed` | 1.0 is Piper's pace; 1.08 is a little brisker |
| `captions` | Formats that get word-by-word captions, for example `["9:16"]`. Each word lights up as it is said. |
| `series` | A JSON file with `intro` and `outro` scene lists, added to every episode that names it. `"introAfterFirst": true` puts the intro after the episode's first scene (the hook). `{episode}`, `{title}` and `{next}` in the series file come from the storyboard. |
| `sfx` | `true` adds a soft, synthesized whoosh at each scene change |
| `music` | `{"file": "music/bed.mp3", "volume": 0.18}`: a bed that dips under the voice and fades out at the end. Use only music you have the rights to. |

### Scenes

| Type | Shows | Settings | Actions |
| --- | --- | --- | --- |
| `card` | A brand card | `template`: `hook` (a question that builds word by word; `fields.text`), `title`, `text`, `metric`, `credit`, `sting` (a two-second series mark) or `outro`; `fields` for its text. `metric` takes `metric` (`cls` or `lcp`) and reads its numbers from `measurements.json`, never from the storyboard. | none |
| `browser` | The product | `system`; `checkout` (a git ref to build and serve first); `network` (`slow-4g`); `overlay: ["layout-shift"]` outlines every element that moves and shows a running CLS; `badge` and `badgeColor` (`before` or `after`). | `goto`, `waitFor`, `scroll`, `click`, `reload` |
| `code` | A real diff | `repo`, `diff` (`a..b`), `files`, `title` | `file` (scroll to the nth file), `scroll` |
| `terminal` | A recorded Claude Code run | `take`: the saved output of `claude -p "<prompt>" --output-format stream-json --verbose`; `prompt`; `redact` (extra `[pattern, replacement]` pairs) | `reveal` (a number, `tools`, `final` or `all`; `every` sets the gap in ms), `scroll` |
| `explain` | An animated diagram on one continuous canvas | `elements`, placed in percent of the frame (`at` as a list, or per format: `{"16:9": [...], "9:16": [...]}`). Kinds: `text`, `box` (`style` `dashed`, `solid` or `fill`), `dot`, `dots` (a scattered field), `axes`, `line` (from and to an element or a point; it draws on), `pill` (parts that light up), `counter`, `check`. | `show`, `hide`, `set` (move, resize, retone or retext an element), `light`, `count`, `pulse` |

### How a `checkout` is served

Each ref gets its own git worktree in your user folder, so the repo you work in is never switched. `install` and `build` run again only when the ref moves to a new commit. Before serving, DOC Docs checks that nothing already answers at `baseUrl`, so a video never shows the wrong build.

## Safety

- **Allowed hosts only.** Phase 1 records and measures on local hosts (`localhost`, `127.0.0.1`, `::1`, `*.localhost`) and on its own generated pages. Anything else is refused in code, whatever the storyboard says.
- **No hand-typed runs.** A terminal scene replays a saved run. The working folder from the run is shown as `~/<folder>`, so local paths do not reach the video.
- **Numbers come from measurement.** The metric card reads `measurements.json`, which records the Lighthouse version, the network profile, the number of runs and the date.

## How it records

Every scene is a web page in headless Chromium (Playwright). Frames come from the Chrome DevTools Protocol screencast as lossless PNGs, each with the time it was drawn. Narration is one cached WAV per sentence. For every 1/30 s of the video, the stitch picks the frame that was on screen at that moment, places each clip where its beat started, and encodes once to H.264, so picture and voice cannot drift.

Labels, captions, badges, zooms and the fade through navy between scenes are drawn by a small script (`hud.js`) injected into every scene page, the product's own pages included, on a layer that the page's layout cannot see. They are in the recorded frames, timed by the same clock as the narration, so nothing is added afterwards.

## Brand

`docdocs/brands/devofcodes/` holds the DevOfCodes look: `brand.css`, the card templates and the fonts (Syne, Literata and JetBrains Mono, all under the SIL Open Font License; see `fonts/`). Set `"brand"` in a storyboard to use another folder with the same files.

## Roadmap

1. **Phase 1 (this):** storyboards, five scene types, Piper, labels and captions, speed-ups and zooms, series intros and outros, stitching with optional sound, `measure`, both formats.
2. **Phase 2:** `docdocs init`, the config-driven `web` adapter, the host allow list in config, a Markdown publisher.
3. **Phase 3:** the feature registry and the author, reviewer and mechanic agents that write guide chapters.
4. **Phase 4:** a Docker image, nightly CI, a WordPress publisher, and change tracking from release diffs.

Not in phase 1 yet: asciinema casts for terminal scenes, and a branded pointer for clicks.

## Licence

MIT. See [LICENSE](LICENSE). Made by Dev of Codes LLC.
