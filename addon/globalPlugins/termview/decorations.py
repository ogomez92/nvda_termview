"""Removal of progress bars, spinners and line drawing from the lines of a snapshot.

Terminal programs draw with characters. A backup or a download shows its progress as a bar of block
characters, ``pip`` and ``rich`` draw theirs with heavy lines, ``docker`` and ``apt`` use runs of
``=`` and ``#`` in brackets, spinners cycle through braille patterns, and tables and panels are
framed with box drawing. On screen this is a picture; read aloud it is dozens of "full block, light
shade" before the numbers that actually say how far along the job is. Removing it leaves the text.

Only the snapshot is affected. Nothing here touches the terminal; taking another snapshot with the
setting cleared brings the drawing back.
"""

import re
from typing import Final

#: The Unicode blocks made of drawing characters only, which never carry words.
_DRAWING_CHARS: Final[str] = (
	"─-╿"  # Box Drawing: table borders, panels, and the bars of pip and rich.
	"▀-▟"  # Block Elements: full and partial blocks and shades, as in tqdm.
	"■-◿"  # Geometric Shapes: squares and circles some bars and spinners use.
	"⠀-⣿"  # Braille Patterns: the spinners of npm, cargo and many others.
	"\U0001fb00-\U0001fbff"  # Symbols for Legacy Computing: finer bar segments.
)

#: A bar drawn in brackets with ASCII, such as ``[=====>    ]`` or ``[####......]``. It must be long
#: enough, and contain enough of the bar characters, not to catch ``[ ]`` or ``[...]`` in a message.
_ASCII_BAR: Final[str] = r"\[(?=[^\]]*[=#>-]{3})[=#>.\- ]{5,}\]"

#: Matches one run of drawing together with the space around it, so that removing it closes the gap.
_DECORATION_RE: Final[re.Pattern[str]] = re.compile(
	rf"[ \t]*(?:[{_DRAWING_CHARS}]+|{_ASCII_BAR})(?:[ \t]*(?:[{_DRAWING_CHARS}]+|{_ASCII_BAR}))*[ \t]*",
)


def stripFromLine(line: str) -> str:
	"""Remove every run of drawing characters in one line.

	:param line: A captured terminal line.
	:return: The line without its drawing, or the line itself if it held none.
	"""
	indent = line[: len(line) - len(line.lstrip())]
	body = line[len(indent) :]
	stripped = _DECORATION_RE.sub(" ", body)
	if stripped == body:
		return line
	stripped = stripped.strip()
	# The line's own indentation is restored, so that indented output keeps its shape.
	return indent + stripped if stripped else ""


def stripFromLines(lines: list[str]) -> list[str]:
	"""Remove every run of drawing characters in a snapshot.

	A line that held nothing but drawing, such as the border of a table, is dropped rather than left
	blank. Lines that were already blank are untouched, so that whether they survive remains the
	business of the ``keepBlankLines`` setting alone.

	:param lines: The captured lines.
	:return: The lines without their drawing.
	"""
	result: list[str] = []
	for line in lines:
		stripped = stripFromLine(line)
		if stripped or not line.strip():
			result.append(stripped)
	return result
