"""Rendering of a terminal snapshot into a document NVDA can present in browse mode.

The document is deliberately plain: ordinary lines live in ``pre`` blocks so that indentation and
blank lines survive, and lines matched by a keyword become real HTML headings. That makes NVDA's
browse mode quick navigation (``h``, ``1`` to ``6``) and the elements list (``NVDA+f7``) work over
terminal output without any further support from the add-on.

Web addresses and email addresses become real links, so that pressing enter on one in browse
mode opens it, the same as on a web page.
"""

import re
import time
from html import escape
from typing import Final

import addonHandler
import nh3

from .capture import Snapshot
from .keywords import KeywordList

addonHandler.initTranslation()


#: The only HTML tags a rendered snapshot uses.
ALLOWED_TAGS: Final[set[str]] = {"p", "pre", "h1", "h2", "h3", "h4", "h5", "h6", "a"}
#: The only attributes a rendered snapshot uses, by tag.
ALLOWED_ATTRIBUTES: Final[dict[str, set[str]]] = {"a": {"href"}}
#: The only URL schemes a link may use. Terminal output is untrusted, so a link to anything else,
#: such as a ``javascript:`` or ``file:`` URL, is dropped by the sanitiser.
ALLOWED_URL_SCHEMES: Final[set[str]] = {"http", "https", "ftp", "mailto"}

#: Text that is turned into a link: a web address with its scheme, one starting with ``www.``, or
#: an email address. Whitespace, quotes and angle brackets always end an address, since they are
#: what terminal output typically surrounds one with. Something shaped like an email address that
#: is really an SSH location, such as ``git@github.com:user/repo.git`` or the user part of an
#: ``ssh://`` URL, is not linked.
_LINK_PATTERN: Final = re.compile(
	r"""
	(?P<url>\b(?:https?|ftp)://[^\s<>"'`]+)
	|(?P<www>\bwww\.[^\s<>"'`]+)
	|(?P<email>(?<![/:])\b[\w.%+-]+@[\w-]+(?:\.[\w-]+)*\.[a-zA-Z]{2,}\b(?!:[\w/~]))
	""",
	re.VERBOSE,
)
#: Punctuation that ends a sentence rather than an address, when it is the last thing matched.
_TRAILING_PUNCTUATION: Final = ".,;:!?*"
#: Closing brackets, which only belong to an address when the address also opens them.
_BRACKET_PAIRS: Final[dict[str, str]] = {")": "(", "]": "[", "}": "{"}


def _trimAddress(address: str) -> str:
	"""Remove trailing characters that surround an address in prose rather than belong to it.

	:param address: The address as matched.
	:return: The address without trailing punctuation or unbalanced closing brackets.
	"""
	while address:
		last = address[-1]
		if last in _TRAILING_PUNCTUATION:
			address = address[:-1]
		elif last in _BRACKET_PAIRS and address.count(last) > address.count(_BRACKET_PAIRS[last]):
			address = address[:-1]
		else:
			break
	return address


def linkify(text: str) -> str:
	"""Escape text for HTML, turning the web and email addresses in it into links.

	:param text: Plain text, such as a terminal line.
	:return: The escaped text, with each address wrapped in an ``a`` element.
	"""
	parts: list[str] = []
	position = 0
	for match in _LINK_PATTERN.finditer(text):
		address = _trimAddress(match.group())
		if not address or match.start() < position:
			continue
		if match.lastgroup == "email":
			href = f"mailto:{address}"
		elif match.lastgroup == "www":
			href = f"http://{address}"
		else:
			href = address
		parts.append(escape(text[position : match.start()]))
		parts.append(f'<a href="{escape(href)}">{escape(address)}</a>')
		position = match.start() + len(address)
	parts.append(escape(text[position:]))
	return "".join(parts)


def sanitize(html: str) -> str:
	"""Sanitise a rendered snapshot before it is presented.

	A snapshot is built entirely from escaped text, so this is defence in depth. Naming the
	permitted tags explicitly also makes the result independent of the sanitiser's default
	policy, which matters because that policy decides whether headings survive at all.

	:param html: The rendered document.
	:return: The document with any tag, attribute or link scheme not explicitly allowed removed.
	"""
	return nh3.clean(
		html,
		tags=ALLOWED_TAGS,
		attributes=ALLOWED_ATTRIBUTES,
		url_schemes=ALLOWED_URL_SCHEMES,
		# A rel attribute means nothing in the review window, and would only add noise.
		link_rel=None,
	)


class RenderedSnapshot:
	"""A snapshot rendered as an HTML document, together with what it contains."""

	__slots__ = ("html", "headingCount", "lineCount")

	def __init__(self, html: str, headingCount: int, lineCount: int) -> None:
		"""
		:param html: The HTML document body to present.
		:param headingCount: How many lines were marked as headings.
		:param lineCount: How many terminal lines the document contains.
		"""
		self.html = html
		self.headingCount = headingCount
		self.lineCount = lineCount


def _formatLine(line: str, number: int, numberWidth: int) -> str:
	"""Prefix a line with its line number.

	:param line: The terminal line.
	:param number: The line's one based position in the snapshot.
	:param numberWidth: The width to pad the number to, so that lines stay aligned.
	:return: The line with its number prefixed.
	"""
	return f"{number:>{numberWidth}}  {line}"


def buildDocument(
	snapshot: Snapshot,
	keywords: KeywordList,
	showLineNumbers: bool = False,
) -> RenderedSnapshot:
	"""Render a captured snapshot as an HTML document.

	:param snapshot: The captured terminal contents.
	:param keywords: The keyword rules deciding which lines become headings.
	:param showLineNumbers: Whether each line is prefixed with its line number.
	:return: The rendered document and a summary of what it contains.
	"""
	numberWidth = len(str(len(snapshot.lines))) if showLineNumbers else 0
	parts: list[str] = []
	pending: list[str] = []
	headingCount = 0

	def flushPending() -> None:
		"""Emit the run of ordinary lines gathered so far as a single preformatted block."""
		if not pending:
			return
		# Two leading newlines, because a newline directly after <pre> is discarded twice over:
		# once by the sanitiser's HTML parser and once by the browser rendering the result.
		# Without them a genuinely blank first line of the block would be swallowed.
		parts.append("<pre>\n\n{}</pre>".format("\n".join(escape(line) for line in pending)))
		pending.clear()

	for index, line in enumerate(snapshot.lines, 1):
		level = keywords.headingLevelFor(line)
		displayed = _formatLine(line, index, numberWidth) if showLineNumbers else line
		if level is None:
			pending.append(displayed)
			continue
		flushPending()
		headingCount += 1
		# A heading with no visible text would be unusable, so fall back to the line number.
		text = displayed.strip() or displayed
		parts.append(f"<h{level}>{linkify(text)}</h{level}>")

	flushPending()
	summary = _buildSummary(snapshot, headingCount)
	return RenderedSnapshot(
		html=summary + "\n" + "\n".join(parts),
		headingCount=headingCount,
		lineCount=len(snapshot.lines),
	)


def _buildSummary(snapshot: Snapshot, headingCount: int) -> str:
	"""Build the introductory paragraphs describing the snapshot.

	Presenting this as document content rather than speaking it means browse mode reads it
	naturally as the window opens, instead of competing with NVDA's own announcement.

	:param snapshot: The captured terminal contents.
	:param headingCount: How many lines were marked as headings.
	:return: One or more HTML paragraphs.
	"""
	paragraphs = [
		# Translators: The first line of a terminal snapshot, naming the terminal it came from
		# and when it was taken. {name} is the terminal's window title
		# and {time} is a local date and time.
		_("Snapshot of {name}, taken at {time}.").format(
			name=snapshot.sourceName,
			time=time.strftime("%c"),
		),
		# Translators: Reported in a terminal snapshot to say how much it contains.
		# {lines} is a number of lines and {headings} is a number of headings.
		_("{lines} lines, {headings} headings.").format(
			lines=len(snapshot.lines),
			headings=headingCount,
		),
	]
	if snapshot.truncated:
		paragraphs.append(
			# Translators: Reported in a terminal snapshot when the oldest lines were left out
			# because of the configured line limit.
			_("The oldest lines were omitted because the snapshot line limit was reached."),
		)
	if headingCount == 0:
		paragraphs.append(
			# Translators: Reported in a terminal snapshot when no keyword matched any line.
			# "Termview" is the name of this add-on's category in NVDA's settings.
			_("No line matched a keyword. Keywords can be added in NVDA's settings, under Termview."),
		)
	return "\n".join(f"<p>{escape(paragraph)}</p>" for paragraph in paragraphs)
