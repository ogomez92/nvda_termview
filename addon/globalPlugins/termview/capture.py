"""Terminal detection and text capture for termview.

Every capture strategy here is deliberately read only with respect to NVDA's own state:

* The legacy Windows console is read through the ``CONOUT$`` handle **NVDA already holds**
  (:mod:`winConsoleHandler`). The add-on never calls ``AttachConsole``/``FreeConsole`` itself,
  because those change process wide state and would detach NVDA from the console it is reading,
  silently breaking console speech until NVDA is restarted.
* UI Automation consoles are read through the object's existing text pattern, so no new UIA
  connection, cache request or event handler is created.
* Nothing moves the caret, the review cursor or the navigator object, and no NVDA class is patched.

Together this means returning to the terminal after taking a snapshot leaves NVDA exactly as it
was before.
"""

import re
from collections.abc import Callable
from typing import Final

import addonHandler
import api
import controlTypes
import textInfos
from logHandler import log
from NVDAObjects import NVDAObject
from NVDAObjects.behaviors import LiveText, Terminal

from .timestamps import stripFromLines

addonHandler.initTranslation()


#: Executable names of applications that host a terminal but whose objects may not always be
#: recognised by role or overlay class alone.
TERMINAL_APP_NAMES: Final[frozenset[str]] = frozenset(
	{
		"alacritty",
		"cmd",
		"conemu",
		"conemu64",
		"conhost",
		"console",
		"consolez",
		"cygwin",
		"fluent",
		"hyper",
		"kitty",
		"mintty",
		"openconsole",
		"powershell",
		"putty",
		"pwsh",
		"tabby",
		"terminus",
		"wezterm",
		"wezterm-gui",
		"windowsterminal",
		"wsl",
		"wt",
	},
)

#: Matches ANSI/VT escape sequences, which some terminals expose as literal text.
_ANSI_ESCAPE_RE: Final[re.Pattern[str]] = re.compile(
	r"\x1b(?:"
	r"\[[0-9;?]*[ -/]*[@-~]"  # CSI sequences, e.g. colours and cursor movement.
	r"|\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC sequences, e.g. window title changes.
	r"|[@-Z\\-_]"  # Two character escape sequences.
	r")",
)
#: Matches control characters that carry no meaning once the text is laid out as lines.
_CONTROL_CHAR_RE: Final[re.Pattern[str]] = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

#: Upper bound on the number of console cells read in a single ``ReadConsoleOutputCharacter`` call.
_CONSOLE_READ_CHUNK_CELLS: Final[int] = 16384


class CaptureError(Exception):
	"""Raised when the contents of a terminal could not be read."""


class Snapshot:
	"""The captured contents of a terminal at a point in time."""

	__slots__ = ("lines", "sourceName", "method", "truncated")

	def __init__(
		self,
		lines: list[str],
		sourceName: str,
		method: str,
		truncated: bool = False,
	) -> None:
		"""
		:param lines: The captured terminal lines, with trailing whitespace already removed.
		:param sourceName: A user visible name for the terminal the snapshot came from.
		:param method: An untranslated identifier of the capture strategy used, for the log.
		:param truncated: Whether older lines were dropped to honour the configured limit.
		"""
		self.lines = lines
		self.sourceName = sourceName
		self.method = method
		self.truncated = truncated


def isTerminalObject(obj: NVDAObject | None) -> bool:
	"""Report whether the given object represents a terminal.

	:param obj: The object to test, which may be ``None``.
	:return: ``True`` if the object looks like a terminal NVDA can read.
	"""
	if obj is None:
		return False
	# Terminal covers the legacy console, UIA consoles, Windows Terminal in diffing mode,
	# PuTTY and anything else built on NVDA's terminal behaviour.
	if isinstance(obj, Terminal):
		return True
	try:
		# Windows Terminal in notifications mode is a plain UIA object that overrides its role.
		if obj.role == controlTypes.Role.TERMINAL:
			return True
	except Exception:
		log.debugWarning("termview: could not read the role of a candidate terminal", exc_info=True)
	appName = getattr(getattr(obj, "appModule", None), "appName", "") or ""
	if appName.lower() in TERMINAL_APP_NAMES:
		# A known terminal host: accept it as long as NVDA has some way to read its text.
		return isinstance(obj, LiveText) or _hasReadableText(obj)
	return False


def _hasReadableText(obj: NVDAObject) -> bool:
	"""Report whether NVDA can produce a text range covering the whole of this object."""
	try:
		obj.makeTextInfo(textInfos.POSITION_ALL)
	except Exception:
		return False
	return True


def findTerminalObject() -> NVDAObject | None:
	"""Locate the terminal the user is currently working in.

	The focus is preferred, then its ancestors (some terminals focus a child of the terminal
	control), then the navigator object, so that object navigation can be used to snapshot a
	terminal that does not have focus.

	:return: The terminal object, or ``None`` if the user is not on a terminal.
	"""
	focus = api.getFocusObject()
	if isTerminalObject(focus):
		return focus
	for ancestor in reversed(api.getFocusAncestors()):
		if isTerminalObject(ancestor):
			return ancestor
	navigator = api.getNavigatorObject()
	if isTerminalObject(navigator):
		return navigator
	return None


def getTerminalName(obj: NVDAObject) -> str:
	"""Build a user visible name for the terminal a snapshot was taken from.

	:param obj: The terminal object.
	:return: The window title where available, falling back to the application name.
	"""
	try:
		foreground = api.getForegroundObject()
		# Only trust the foreground title when it belongs to the terminal being captured, which it
		# does not when a background terminal was reached with object navigation.
		if foreground.processID == obj.processID and foreground.name:
			return foreground.name
	except Exception:
		log.debugWarning("termview: could not read the terminal's window title", exc_info=True)
	appName = getattr(getattr(obj, "appModule", None), "appName", "") or ""
	if appName:
		return appName
	# Translators: Used in place of the terminal's name when it could not be determined.
	return _("Terminal")


def _captureLegacyConsole(obj: NVDAObject) -> str | None:
	"""Read the whole screen buffer of a legacy Windows console.

	This reuses the console handle NVDA opened when it attached to the console, so that the
	add-on never changes which console NVDA's own process is attached to.

	:param obj: The terminal object.
	:return: The full buffer text, or ``None`` if this object is not the console NVDA is attached to.
	"""
	try:
		import winConsoleHandler
		import wincon
	except ImportError:
		return None
	consoleObject = getattr(winConsoleHandler, "consoleObject", None)
	handle = getattr(winConsoleHandler, "consoleOutputHandle", None)
	if consoleObject is None or not handle:
		return None
	windowHandle = getattr(obj, "windowHandle", None)
	if windowHandle is None or getattr(consoleObject, "windowHandle", None) != windowHandle:
		return None
	try:
		info = wincon.GetConsoleScreenBufferInfo(handle)
		width = int(info.dwSize.x)
		height = int(info.dwSize.y)
		if width <= 0 or height <= 0:
			return None
		rowsPerChunk = max(1, min(height, _CONSOLE_READ_CHUNK_CELLS // width))
		lines: list[str] = []
		for firstRow in range(0, height, rowsPerChunk):
			rows = min(rowsPerChunk, height - firstRow)
			text = wincon.ReadConsoleOutputCharacter(handle, width * rows, 0, firstRow)
			lines.extend(text[offset : offset + width] for offset in range(0, len(text), width))
	except Exception:
		log.debugWarning("termview: could not read the legacy console screen buffer", exc_info=True)
		return None
	return "\n".join(lines)


def _captureUIADocumentRange(obj: NVDAObject) -> str | None:
	"""Read the whole UI Automation text document, including the scrollback.

	NVDA deliberately bounds a console's ``POSITION_ALL`` range to the visible screen, so the
	document range is queried directly to reach text that has scrolled off.

	:param obj: The terminal object.
	:return: The document text, or ``None`` if the object exposes no usable text pattern.
	"""
	textPattern = getattr(obj, "UIATextPattern", None)
	if not textPattern:
		return None
	try:
		documentRange = textPattern.DocumentRange
		if not documentRange:
			return None
		return documentRange.GetText(-1)
	except Exception:
		log.debugWarning("termview: could not read the UIA document range", exc_info=True)
		return None


def _captureVisibleText(obj: NVDAObject) -> str | None:
	"""Read the text NVDA itself would review, which for a console is the visible screen.

	:param obj: The terminal object.
	:return: The text of the object, or ``None`` if it could not be read.
	"""
	try:
		return obj.makeTextInfo(textInfos.POSITION_ALL).text
	except Exception:
		log.debugWarning("termview: could not read the object's text", exc_info=True)
		return None


def normaliseText(
	text: str,
	keepBlankLines: bool = True,
	stripTimestamps: bool = True,
) -> list[str]:
	"""Turn raw captured text into clean lines suitable for presentation.

	:param text: The raw text as read from the terminal.
	:param keepBlankLines: Whether blank lines within the output are preserved.
	:param stripTimestamps: Whether dates and times are removed from each line.
	:return: The cleaned lines, with leading and trailing blank lines removed.
	"""
	text = text.replace("\r\n", "\n").replace("\r", "\n")
	# Strip escape sequences before control characters, so that the escape byte introducing a
	# sequence is not removed before the sequence itself can be recognised.
	text = _ANSI_ESCAPE_RE.sub("", text)
	text = _CONTROL_CHAR_RE.sub("", text)
	lines = [line.rstrip() for line in text.split("\n")]
	if stripTimestamps:
		# Before the blank lines are dealt with, because a line that held nothing but a timestamp
		# disappears here and should not leave a gap behind for keepBlankLines to argue over.
		lines = stripFromLines(lines)
	while lines and not lines[0].strip():
		del lines[0]
	while lines and not lines[-1].strip():
		del lines[-1]
	if not keepBlankLines:
		lines = [line for line in lines if line.strip()]
	return lines


def captureSnapshot(
	obj: NVDAObject,
	includeScrollback: bool = True,
	keepBlankLines: bool = True,
	stripTimestamps: bool = True,
	maxLines: int = 0,
) -> Snapshot:
	"""Capture the contents of a terminal.

	:param obj: The terminal object, as returned by :func:`findTerminalObject`.
	:param includeScrollback: Whether to capture the whole buffer rather than just the
		visible screen.
	:param keepBlankLines: Whether blank lines within the output are preserved.
	:param stripTimestamps: Whether dates and times are removed from each line, so that a log is
		read as its messages rather than its clock.
	:param maxLines: If greater than zero, keep only this many lines, dropping the oldest.
	:return: The captured snapshot.
	:raises CaptureError: If no capture strategy could read any text.
	"""
	attempts: list[tuple[str, Callable[[], str | None]]] = []
	if includeScrollback:
		# Both of these reach text that has scrolled off the visible screen.
		attempts.append(("legacy console buffer", lambda: _captureLegacyConsole(obj)))
		attempts.append(("UIA document range", lambda: _captureUIADocumentRange(obj)))
	# NVDA's own text range always works, but for a console it covers the visible screen only.
	attempts.append(("object text", lambda: _captureVisibleText(obj)))

	for method, capture in attempts:
		raw = capture()
		if not raw:
			continue
		lines = normaliseText(
			raw,
			keepBlankLines=keepBlankLines,
			stripTimestamps=stripTimestamps,
		)
		if not lines:
			continue
		truncated = False
		if maxLines > 0 and len(lines) > maxLines:
			lines = lines[-maxLines:]
			truncated = True
		log.debug(f"termview: captured {len(lines)} lines using the {method}")
		return Snapshot(lines, getTerminalName(obj), method, truncated)

	raise CaptureError(
		# Translators: Reported when the add-on could not read any text from the terminal.
		_("The terminal appears to be empty, or its text could not be read."),
	)
