"""The window a snapshot is presented in.

NVDA's own :func:`ui.browseableMessage` would open this window, and this module works exactly as it
does, with one difference: NVDA lays the Copy and Close buttons out below the message, and a
snapshot is thousands of lines long, so those buttons sit at the end of a very long journey. The
template here puts them, and the separator that follows them, before the snapshot instead.

The window is an MSHTML dialog, the same kind NVDA opens. That is what gives NVDA a document to
build a browse mode buffer from; a window built out of ordinary controls would not be readable that
way.
"""

import os
from ctypes import POINTER, WINFUNCTYPE, byref, windll
from ctypes.wintypes import DWORD, HWND, LPCWSTR, LPWSTR
from typing import Any, Final

import addonHandler
import comtypes.client
import gui
from comtypes import HRESULT, IUnknown
from comtypes.automation import VARIANT

from .render import sanitize

addonHandler.initTranslation()

#: The window's markup, which lives beside this module so that the dialog belongs to the add-on
#: rather than to the NVDA it happens to be running under.
TEMPLATE_PATH: Final = os.path.join(os.path.dirname(os.path.abspath(__file__)), "message.html")

#: ``CreateURLMonikerEx`` flag: the URL is complete, rather than relative to a base moniker.
_URL_MK_UNIFORM: Final = 1
#: ``ShowHTMLDialogEx`` flag: show the window without blocking NVDA's main thread.
_HTMLDLG_MODELESS: Final = 64
#: ``ShowHTMLDialogEx`` options: a window the user can resize, and no help button in its title bar.
_DIALOG_OPTIONS: Final = "resizable:yes;help:no"

# The two functions the window is made of. Both take the URL moniker naming the template: one
# creates it, the other opens the dialog it names. The moniker is only ever passed between them,
# so it is typed as a plain COM pointer rather than as an ``IMoniker``, which saves depending on
# NVDA's ``objidl`` and still releases the moniker when it goes out of scope.
_createURLMonikerEx = WINFUNCTYPE(None)(("CreateURLMonikerEx", windll.urlmon))
_createURLMonikerEx.restype = HRESULT
_createURLMonikerEx.argtypes = (POINTER(IUnknown), LPCWSTR, POINTER(POINTER(IUnknown)), DWORD)

_showHTMLDialogEx = WINFUNCTYPE(None)(("ShowHTMLDialogEx", windll.mshtml))
_showHTMLDialogEx.restype = HRESULT
_showHTMLDialogEx.argtypes = (
	HWND,
	POINTER(IUnknown),
	DWORD,
	POINTER(VARIANT),
	LPWSTR,
	POINTER(VARIANT),
)


def _buildDialogArguments(html: str, title: str) -> Any:
	"""Collect everything the window displays into the object its template reads.

	:param html: The rendered document, which is sanitised here.
	:param title: The window's title.
	:return: A ``Scripting.Dictionary`` to hand to the window as its dialog arguments.
	"""
	args = comtypes.client.CreateObject("Scripting.Dictionary")
	args.add("title", title)
	args.add("message", sanitize(html))
	args.add(
		"copyButtonText",
		# Translators: The label of the button in the review window that copies the snapshot.
		_("Copy"),
	)
	args.add(
		"copyButtonAcceleratorAccessibilityLabel",
		# Translators: The keystroke that copies the snapshot, reported after the Copy button's
		# label so that it can be used without reaching the button.
		_("control+shift+c"),
	)
	args.add(
		"closeButtonText",
		# Translators: The label of the button in the review window that closes it.
		_("Close"),
	)
	args.add(
		"copySuccessfulAlertText",
		# Translators: Reported in the review window once the snapshot has been copied.
		_("Text copied."),
	)
	args.add(
		"copyFailedAlertText",
		# Translators: Reported in the review window when the snapshot could not be copied.
		_("Couldn't copy to clipboard."),
	)
	return args


def showReview(html: str, title: str) -> None:
	"""Present a rendered snapshot in the review window.

	:param html: The rendered document, which is sanitised before it is displayed.
	:param title: The window's title.
	:raise LookupError: If the add-on is missing its template.
	:raise comtypes.COMError: If Windows would not open the window.
	"""
	if not os.path.isfile(TEMPLATE_PATH):
		raise LookupError(f"the review window's template is missing: {TEMPLATE_PATH}")
	moniker = POINTER(IUnknown)()
	_createURLMonikerEx(None, TEMPLATE_PATH, byref(moniker), _URL_MK_UNIFORM)
	dialogArguments = VARIANT(_buildDialogArguments(html, title))
	# NVDA has to be told that a window is being opened in front of it, so that it handles focus
	# while the window is up and gives it back afterwards.
	gui.mainFrame.prePopup()
	try:
		_showHTMLDialogEx(
			gui.mainFrame.Handle,
			moniker,
			_HTMLDLG_MODELESS,
			byref(dialogArguments),
			_DIALOG_OPTIONS,
			None,
		)
	finally:
		gui.mainFrame.postPopup()
