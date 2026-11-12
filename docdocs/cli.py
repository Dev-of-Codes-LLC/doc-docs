"""docdocs: the command line.

    docdocs check   <storyboard.json>
    docdocs build   <storyboard.json> [--scenes 2,5] [--format 16:9] [--voice silent] [--only record|stitch]
    docdocs measure <storyboard.json> [--runs 3]
    docdocs voices  install <voice> | list
"""

import argparse
import asyncio
import sys

from docdocs import __version__
from docdocs.storyboard import FORMATS, StoryboardError, load


def _scenes(value: str) -> set[int]:
    try:
        return {int(x) for x in value.split(",") if x.strip()}
    except ValueError:
        raise argparse.ArgumentTypeError("use scene numbers like 2 or 2,5") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="docdocs", description="DOC Docs: narrated product videos from a storyboard.")
    parser.add_argument("--version", action="version", version=f"docdocs {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check", help="check a storyboard without recording")
    p.add_argument("storyboard")

    p = sub.add_parser("build", help="record the scenes and stitch the video")
    p.add_argument("storyboard")
    p.add_argument("--scenes", type=_scenes, help="re-record only these scenes (1-based), keep the rest")
    p.add_argument("--format", choices=list(FORMATS), action="append", help="only this format (repeatable)")
    p.add_argument("--voice", help="override the storyboard's voice, e.g. silent")
    p.add_argument("--only", choices=["record", "stitch"], help="run one half of the build")
    p.add_argument("--gpu", action="store_true", default=None,
                   help="record with the browser on the machine's GPU, for a product that draws in 3D; "
                        "the storyboard's \"gpu\" setting does the same")

    p = sub.add_parser("measure", help="run Lighthouse on each ref and write measurements.json")
    p.add_argument("storyboard")
    p.add_argument("--runs", type=int)

    p = sub.add_parser("voices", help="install or list Piper voices")
    p.add_argument("action", choices=["install", "list"])
    p.add_argument("name", nargs="?")

    args = parser.parse_args(argv)
    try:
        return _run(args)
    except StoryboardError as e:
        print(f"storyboard: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception as e:  # noqa: BLE001 - one clear line for the user, not a trace
        print(f"docdocs: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


def _run(args) -> int:
    if args.command == "voices":
        from docdocs.voice import install, voices_dir

        if args.action == "list":
            for model in sorted(voices_dir().glob("*.onnx")):
                print(model.stem)
            return 0
        if not args.name:
            print("name a voice, for example: docdocs voices install kokoro", file=sys.stderr)
            return 2
        print(install(args.name))
        return 0

    sb = load(args.storyboard)

    if args.command == "check":
        print(f"{sb.id}: {len(sb.scenes)} scenes, formats {', '.join(f.name for f in sb.formats)}, voice {sb.voice}"
              + (", on the GPU" if sb.gpu else ""))
        for s in sb.scenes:
            said = sum(1 for b in s.beats if b.say)
            print(f"  {s.index:2d}. {s.type:<8} {said} narrated beat(s)")
        return 0

    if args.command == "measure":
        from docdocs.measure import measure

        measure(sb, runs=args.runs)
        return 0

    from docdocs.mux import stitch
    from docdocs.recorder import record
    from docdocs.voice import Voice

    formats = [FORMATS[f] for f in args.format] if args.format else sb.formats
    if args.only != "stitch":
        voice = Voice(args.voice) if args.voice else None
        asyncio.run(record(sb, only=args.scenes, formats=formats, voice=voice, gpu=args.gpu))
    if args.only != "record":
        for fmt in formats:
            mp4, srt = stitch(sb, fmt)
            print(f"[{fmt.name}] {mp4}\n[{fmt.name}] {srt}")
    return 0
