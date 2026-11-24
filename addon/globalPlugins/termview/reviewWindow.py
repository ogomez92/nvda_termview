"""The window a snapshot is presented in.

NVDA's own :func:`ui.browseableMessage` would open this window, and this module works exactly as it
does, with one difference: NVDA lays the Copy and Close buttons out below the message, and a
snapshot is thousands of lines long, so those buttons sit at the end of a very long journey. The
template here puts them, and the separator that follows them, before the snapshot instead.

The window is an MSHTML dialog, the same kind NVDA opens. That is what gives NVDA a document to
build a browse mode buffer from; a window built out of ordinary controls would not be readable that
way.

The browse mode document NVDA builds for the window is also replaced with one that never breaks a
long line into pieces, whatever NVDA's "Maximum number of characters on one line" setting says.
Terminal output has its own line structure, and a line only makes sense read whole.
"""

import os
from ctypes import POINTER, WINFUNCTYPE, byref, c_int, windll
from ctypes.wintypes import DWORD, HWND, LPCWSTR, LPWSTR
from typing import Any, Final

import addonHandler
import comtypes.client
import config
import gui
import NVDAHelper
import virtualBuffers.MSHTML
import winUser
from comtypes import COMError, HRESULT, IUnknown
from comtypes.automation import VARIANT
from NVDAObjects import NVDAObject

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

#: The window class of the frame ``ShowHTMLDialogEx`` opens.
_DIALOG_WINDOW_CLASS: Final = "Internet Explorer_TridentDlgFrame"
#: The window class of the document inside that frame.
_DOCUMENT_WINDOW_CLASS: Final = "Internet Explorer_Server"
#: The id of the template's body element. NVDA's own message windows are the same kind of dialog,
#: so this is what tells the review window apart from them.
_BODY_ID: Final = "termviewReviewBody"

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


class _UnwrappedTextInfo(virtualBuffers.MSHTML.MSHTMLTextInfo):
	"""Text in the review window, where a line always runs to the end of the terminal line."""

	def _getLineOffsets(self, offset: int) -> tuple[int, int]:
		lineStart = c_int()
		lineEnd = c_int()
		NVDAHelper.localLib.VBuf_getLineOffsets(
			self.obj.VBufHandle,
			offset,
			# A maximum line length of 0 means no maximum, so lines end only where the text does.
			0,
			config.conf["virtualBuffers"]["useScreenLayout"],
			byref(lineStart),
			byref(lineEnd),
		)
		return lineStart.value, lineEnd.value


class _UnwrappedBuffer(virtualBuffers.MSHTML.MSHTML):
	"""The review window's browse mode document, which never breaks long lines."""

	TextInfo = _UnwrappedTextInfo


class ReviewDocument(NVDAObject):
	"""Overlay for the review window's document, giving it a browse mode buffer without wrapping."""

	def _get_treeInterceptorClass(self) -> type:
		cls = super().treeInterceptorClass
		if isinstance(cls, type) and issubclass(cls, virtualBuffers.MSHTML.MSHTML):
			return _UnwrappedBuffer
		return cls


def isReviewDocument(obj: NVDAObject) -> bool:
	"""Whether an object belongs to the document of a review window.

	The cheap window class checks come first, so that only objects in an HTML dialog ever cost a
	call into the document.

	:param obj: The object being created.
	:return: ``True`` if the object is part of a termview review window.
	"""
	# Only window objects have a window class; anything else cannot be the review window.
	if getattr(obj, "windowClassName", None) != _DOCUMENT_WINDOW_CLASS:
		return False
	rootWindow = winUser.getAncestor(obj.windowHandle, winUser.GA_ROOT)
	if winUser.getClassName(rootWindow) != _DIALOG_WINDOW_CLASS:
		return False
	try:
		return obj.HTMLNode.document.body.id == _BODY_ID
	except (AttributeError, COMError, NameError):
		return False


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
