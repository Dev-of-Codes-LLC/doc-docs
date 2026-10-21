"""The host allow list.

DOC Docs records and measures only on hosts it is told it may use. This is
an allow list, not a deny list: a host nobody named is refused. In phase 1
the only hosts are local ones. The check is in code, so no storyboard can
turn it off.
"""

from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class HostNotAllowed(Exception):
    pass


def check_url(url: str, file_root: Path | None = None) -> None:
    """Raise HostNotAllowed unless url is a local host, or a file under file_root."""
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https"):
        host = (parsed.hostname or "").lower()
        if host in LOCAL_HOSTS or host.endswith(".localhost"):
            return
        raise HostNotAllowed(f"{url}: {host or '(no host)'} is not on the allow list (phase 1 allows local hosts only)")
    if parsed.scheme == "file" and file_root is not None:
        path = Path(url2pathname(parsed.path))
        try:
            path.resolve().relative_to(file_root.resolve())
            return
        except ValueError:
            pass
        raise HostNotAllowed(f"{url}: only files under {file_root} may be opened")
    if url == "about:blank":
        return
    raise HostNotAllowed(f"{url}: scheme {parsed.scheme!r} is not allowed")
