"""termview: review a terminal's output in a browse mode window.

Pressing the review gesture takes a snapshot of the terminal the user is on and presents it in
NVDA's browsable message window. Lines matching a configured keyword become headings, so the
interesting parts of a long build log or test run can be reached with browse mode heading
navigation and the elements list.

Taking a snapshot leaves NVDA's own state untouched; see :mod:`.capture` for why that matters.
"""

import os
import sys

import addonHandler
import api
import globalPluginHandler
import gui
import ui
import wx
from gui.settingsDialogs import NVDASettingsDialog
from logHandler import log
from NVDAObjects import NVDAObject
from NVDAObjects.behaviors import LiveText
from scriptHandler import script

#: The directory holding this plugin, e.g. ``...\addons\termview\globalPlugins\termview``.
ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
#: The root of the installed add-on, e.g. ``...\addons\termview``.
ROOT_ADDON_DIR = "\\".join(ADDON_DIR.split(os.sep)[:-2])
#: Where ``uv sync`` places this add-on's runtime dependencies.
UV_PACKAGES_DIR = os.path.join(ROOT_ADDON_DIR, ".venv", "Lib", "site-packages")

sys.path.insert(0, UV_PACKAGES_DIR)
try:
	# Import dependencies managed by uv here. termview needs none beyond NVDA and the standard
	# library, so this block is empty; adding a dependency is a line in pyproject.toml and an
	# import here.
	pass
finally:
	# The entry is removed again immediately so that this add-on's dependencies can never shadow
	# modules belonging to NVDA or to another add-on, a common cause of add-on conflicts.
	sys.path.remove(UV_PACKAGES_DIR)

addonHandler.initTranslation()

from .capture import CaptureError, captureSnapshot, findTerminalObject  # noqa: E402
from .conf import getConf, initialize as initializeConfig  # noqa: E402
from .keywords import KeywordList  # noqa: E402
from .render import buildDocument, sanitize  # noqa: E402
from .settingsGui import TermviewSettingsPanel  # noqa: E402

try:
	ADDON_INFO = addonHandler.Addon(ROOT_ADDON_DIR).manifest
except Exception:
	# Running from a source tree rather than an installed add-on.
	log.debugWarning(f"termview: no add-on manifest found at {ROOT_ADDON_DIR}", exc_info=True)
	ADDON_INFO = None


class _TerminalMonitorGuard:
	"""Keeps a terminal speaking its new output after the review window is closed.

	NVDA stops monitoring a terminal for new text when it loses focus and starts again when it
	regains it, which is all that is normally needed. This guard is a safety net: after a snapshot
	it remembers the terminal, and when focus returns there it checks that monitoring really did
	resume, restarting it only if it did not. It never starts monitoring an object that does not
	have focus, and disarms itself as soon as the terminal has been checked once.
	"""

	def __init__(self) -> None:
		#: The window the guard is waiting to see focused again, or ``None`` when disarmed.
		self._windowHandle: int | None = None

	def watch(self, obj: NVDAObject) -> None:
		"""Begin watching the terminal a snapshot was just taken from.

		:param obj: The terminal object. Objects that NVDA does not monitor are ignored.
		"""
		self.cancel()
		if not isinstance(obj, LiveText):
			# Windows Terminal in notifications mode, and anything else NVDA does not monitor for
			# new text, has nothing that could need restarting.
			return
		self._windowHandle = getattr(obj, "windowHandle", None) or None

	def cancel(self) -> None:
		"""Stop watching."""
		self._windowHandle = None

	def onFocusGained(self, obj: NVDAObject) -> None:
		"""Check a terminal that has just regained focus, after NVDA has handled the event.

		:param obj: The object that gained focus.
		"""
		if self._windowHandle is None or getattr(obj, "windowHandle", None) != self._windowHandle:
			return
		# The terminal is back, so the guard has done its job either way.
		self.cancel()
		# A missing attribute reads as False rather than None, so that a future NVDA which tracks
		# monitoring differently is left alone instead of having a second monitor thread started.
		if getattr(obj, "_monitorThread", False) is not None:
			return
		if obj is not api.getFocusObject():
			# Focus moved on again before this ran; monitoring an unfocused terminal would be wrong.
			return
		log.debugWarning("termview: terminal monitoring did not resume by itself; restarting it")
		try:
			obj.startMonitoring()
		except Exception:
			log.error("termview: could not restart terminal monitoring", exc_info=True)


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	"""Adds the terminal review command and the termview settings category."""

	# Translators: The category termview's commands appear under in NVDA's input gestures dialog.
	scriptCategory = _("Termview")

	def __init__(self) -> None:
		super().__init__()
		initializeConfig()
		NVDASettingsDialog.categoryClasses.append(TermviewSettingsPanel)
		self._monitorGuard = _TerminalMonitorGuard()
		version = ADDON_INFO["version"] if ADDON_INFO else "source"
		log.debug(f"termview {version} loaded")

	def terminate(self) -> None:
		"""Undo everything done in :meth:`__init__` when NVDA exits or the add-on is disabled."""
		self._monitorGuard.cancel()
		try:
			NVDASettingsDialog.categoryClasses.remove(TermviewSettingsPanel)
		except ValueError:
			log.debugWarning("termview: settings category was already removed")
		super().terminate()

	def event_gainFocus(self, obj, nextHandler) -> None:
		"""Let NVDA handle the focus change, then run the terminal monitor guard.

		The guard has to run after ``nextHandler``, because it is NVDA's own handling of this very
		event that restarts monitoring on a terminal; only once that has run can the guard tell
		whether it worked.
		"""
		nextHandler()
		try:
			self._monitorGuard.onFocusGained(obj)
		except Exception:
			# A focus event must never fail because of this add-on.
			log.error("termview: the terminal monitor guard failed", exc_info=True)

	@script(
		# Translators: The description of the termview command, shown in NVDA's input gestures dialog.
		description=_("Takes a snapshot of the current terminal and opens it in a review window"),
		gesture="kb:NVDA+shift+v",
	)
	def script_reviewTerminal(self, gesture) -> None:
		"""Capture the current terminal and present it in a browse mode window."""
		obj = findTerminalObject()
		if obj is None:
			ui.message(
				# Translators: Reported when the review command is used somewhere other than a terminal.
				_("Not a terminal window"),
			)
			return
		conf = getConf()
		try:
			snapshot = captureSnapshot(
				obj,
				includeScrollback=conf["includeScrollback"],
				keepBlankLines=conf["keepBlankLines"],
				stripTimestamps=conf["stripTimestamps"],
				maxLines=conf["maxLines"],
			)
		except CaptureError as e:
			ui.message(str(e))
			return
		except Exception:
			log.error("termview: unexpected error while capturing the terminal", exc_info=True)
			ui.message(
				# Translators: Reported when a terminal could not be captured because of an error.
				_("The terminal could not be read. See NVDA's log for details."),
			)
			return
		document = buildDocument(
			snapshot,
			KeywordList.load(),
			showLineNumbers=conf["showLineNumbers"],
		)
		log.debug(
			f"termview: presenting {document.lineCount} lines "
			f"with {document.headingCount} headings, captured via the {snapshot.method}",
		)
		# Watch the terminal before the window opens, so the guard is already in place by the
		# time focus leaves it.
		self._monitorGuard.watch(obj)
		ui.browseableMessage(
			document.html,
			# Translators: The title of the terminal review window.
			# {name} is the title of the terminal window the snapshot was taken from.
			title=_("Termview: {name}").format(name=snapshot.sourceName),
			isHtml=True,
			closeButton=True,
			copyButton=True,
			sanitizeHtmlFunc=sanitize,
		)

	@script(
		# Translators: The description of a termview command, shown in NVDA's input gestures dialog.
		description=_("Opens the termview settings"),
	)
	def script_openSettings(self, gesture) -> None:
		"""Open NVDA's settings at the termview category."""
		wx.CallAfter(
			gui.mainFrame.popupSettingsDialog,
			NVDASettingsDialog,
			TermviewSettingsPanel,
		)
