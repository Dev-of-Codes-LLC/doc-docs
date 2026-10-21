"""Check out a git ref, build it and serve it, for one browser scene or one measurement.

Each ref gets its own git worktree in the user folder, so the repo you are
working in is never switched or touched. Install and build run again only
when the ref points at a new commit.

A system in the storyboard says how:

    "demo": {"repo": "../..", "baseUrl": "http://localhost:4173",
             "install": "npm ci", "build": "npm run build", "serve": "npm run preview"}
"""

import hashlib
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from docdocs.hosts import check_url
from docdocs.paths import user_dir


class ServeError(Exception):
    pass


def answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2):
            return True
    except urllib.error.HTTPError:
        return True  # something is listening
    except OSError:
        return False


def _run(cmd: str, cwd: Path, log) -> None:
    log(f"  $ {cmd}")
    result = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        tail = "\n".join((result.stdout + result.stderr).splitlines()[-20:])
        raise ServeError(f"{cmd!r} failed in {cwd} (exit {result.returncode}):\n{tail}")


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise ServeError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


class RefServer:
    def __init__(self, system: dict, repo: Path, ref: str | None, log=print):
        self.system = system
        self.base_url = system["baseUrl"]
        check_url(self.base_url)
        self.repo = repo
        self.ref = ref
        self.log = log
        self.proc: subprocess.Popen | None = None

    def worktree(self) -> Path:
        repo_key = hashlib.sha256(str(self.repo.resolve()).encode()).hexdigest()[:10]
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", self.ref)
        return user_dir() / "worktrees" / f"{self.repo.name}-{repo_key}" / safe

    def prepare(self) -> Path:
        if not self.ref:
            if self.system.get("build"):
                _run(self.system["build"], self.repo, self.log)
            return self.repo
        sha = _git(self.repo, "rev-parse", f"{self.ref}^{{commit}}")
        wt = self.worktree()
        if not wt.exists():
            wt.parent.mkdir(parents=True, exist_ok=True)
            self.log(f"  worktree for {self.ref} at {wt}")
            _git(self.repo, "worktree", "add", "--detach", str(wt), sha)
        elif _git(wt, "rev-parse", "HEAD") != sha:
            _git(wt, "checkout", "--detach", sha)
        marker = wt / ".docdocs-built"
        if not marker.exists() or marker.read_text().strip() != sha:
            if self.system.get("install"):
                _run(self.system["install"], wt, self.log)
            if self.system.get("build"):
                _run(self.system["build"], wt, self.log)
            marker.write_text(sha)
        return wt

    def __enter__(self) -> "RefServer":
        if answers(self.base_url):
            raise ServeError(f"something already answers at {self.base_url}. Stop it first, so the video shows the right build.")
        cwd = self.prepare()
        self.log(f"  serving {self.ref or 'the working tree'} at {self.base_url}")
        self._log_path = cwd / ".docdocs-serve.log"
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        self.proc = subprocess.Popen(
            self.system["serve"], cwd=cwd, shell=True, creationflags=flags,
            stdout=open(self._log_path, "w"), stderr=subprocess.STDOUT,
            start_new_session=sys.platform != "win32",
        )
        deadline = time.time() + float(self.system.get("startTimeout", 90))
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise ServeError(f"{self.system['serve']!r} exited early:\n{self._log_path.read_text(errors='replace')[-2000:]}")
            if answers(self.base_url):
                return self
            time.sleep(0.4)
        self.__exit__(None, None, None)
        raise ServeError(f"{self.base_url} did not answer within the start timeout")

    def __exit__(self, *exc) -> None:
        if self.proc and self.proc.poll() is None:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True)
            else:
                os.killpg(self.proc.pid, signal.SIGTERM)
            self.proc.wait(timeout=15)
        deadline = time.time() + 10
        while answers(self.base_url) and time.time() < deadline:
            time.sleep(0.3)
