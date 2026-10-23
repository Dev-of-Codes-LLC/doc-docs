"""Scene recorders. Each one opens its page, starts the capture, plays the beats and returns a take."""

from docdocs.scenes.browser import record as record_browser
from docdocs.scenes.card import record as record_card
from docdocs.scenes.code import record as record_code
from docdocs.scenes.explain import record as record_explain
from docdocs.scenes.terminal import record as record_terminal

RECORDERS = {
    "card": record_card,
    "browser": record_browser,
    "code": record_code,
    "terminal": record_terminal,
    "explain": record_explain,
}
