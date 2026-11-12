"""Record on the machine's own GPU.

Every scene is a page in headless Chromium, and headless Chromium draws
WebGL in software unless it is told otherwise. For a card, a diff or an
ordinary web page that makes no difference. For a product that draws in 3D
it makes all of it: the scene plays as a slide show, and a product that
looks at the renderer's name sees a software one and may show its lightest
version.

`"gpu": true` in a storyboard, or `docdocs build --gpu`, launches the
browser with the flags below. Nothing else about the recording changes.

Checked on Windows 11 with Direct3D 11 (a GeForce RTX 3050): a WebGL scene
that recorded at 0.6 to 2.7 frames a second in software recorded at 25 to 49
(README, "On the GPU"). On macOS the flags ask for Metal and on Linux for
OpenGL; neither is checked.
Where there is no GPU, or the flags do not take, Chromium falls back to
software, and the build says so and carries on.
"""

import re
import sys

# ANGLE is Chromium's layer between WebGL and the system's graphics API.
_BACKENDS = {"win32": "d3d11", "darwin": "metal"}

_SOFTWARE = re.compile(r"swiftshader|llvmpipe|software|basic render", re.IGNORECASE)

_RENDERER = """() => {
  const gl = document.createElement('canvas').getContext('webgl2') || document.createElement('canvas').getContext('webgl')
  if (!gl) return null
  const info = gl.getExtension('WEBGL_debug_renderer_info')
  return String(gl.getParameter(info ? info.UNMASKED_RENDERER_WEBGL : gl.RENDERER))
}"""


def launch_args(gpu: bool, platform: str = sys.platform) -> list[str]:
    """The extra arguments Chromium is launched with: none, unless the GPU is asked for."""
    if not gpu:
        return []
    return [f"--use-angle={_BACKENDS.get(platform, 'gl')}", "--enable-gpu", "--ignore-gpu-blocklist"]


def is_software(renderer: str | None) -> bool:
    """Whether a WebGL renderer's name is a software one (or there is no WebGL at all)."""
    return not renderer or bool(_SOFTWARE.search(renderer))


async def renderer_of(browser) -> str | None:
    """The name of what this browser draws WebGL with, or None if it has no WebGL."""
    page = await browser.new_page()
    try:
        return await page.evaluate(_RENDERER)
    finally:
        await page.close()


def report(renderer: str | None) -> str:
    """One line for the build log: what the GPU option got."""
    if is_software(renderer):
        return f"gpu: asked for, but the browser still draws in software ({renderer or 'no WebGL'}). Recording carries on."
    return f"gpu: {renderer}"
