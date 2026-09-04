"""Removal of dates, times and timestamps from the lines of a snapshot.

Logs are dominated by timestamps. A build log, a syslog or a service's output tends to open every
line with a date and a time that differs from the twenty lines around it only in the seconds, and
read aloud that is the first thing heard on each line, ahead of the message itself. Removing them
makes a long log much quicker to review, and browse mode's find still reaches everything that
matters.

Only the snapshot is affected. Nothing here touches the terminal, which keeps its output exactly as
it produced it; taking another snapshot with the setting cleared brings the timestamps back.

The patterns are deliberately shy of anything that merely looks like a time. A bare ``1:30`` may be a
duration or a ratio, so a clock time on its own is recognised only when seconds or a meridiem make it
unmistakable, dotted numbers such as ``1.2.34`` and ``192.168.0.10`` are never read as dates, and a
date glued to surrounding text, as in ``build-2026-09-02.log``, is left alone.
"""

import re
from typing import Final

#: A year, limited to the range a log realistically carries.
_YEAR: Final[str] = r"(?:19|20)\d{2}"
#: A month name or its usual three letter abbreviation, with an optional full stop.
_MONTH_NAME: Final[str] = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
#: A weekday name or its usual three letter abbreviation, with an optional full stop.
_DAY_NAME: Final[str] = r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\.?"
#: A day of the month, with or without a leading zero.
_DAY: Final[str] = r"(?:[0-2]?\d|3[01])"
#: Hours and minutes.
_CLOCK: Final[str] = r"[0-2]?\d:[0-5]\d"
#: Seconds, with the fractional part logging libraries add after either a full stop or a comma.
_SECONDS: Final[str] = r"(?::[0-5]\d(?:[.,]\d{1,9})?)"
#: ``am`` or ``pm``, however it is punctuated.
_MERIDIEM: Final[str] = r"(?:[ \t]?[ap]\.?m\.?)"
#: A time zone, restricted to forms that cannot be confused with an ordinary word.
_ZONE: Final[str] = r"(?:[ \t]?(?:Z|UTC|GMT|[+-]\d{2}:?\d{2}))"
#: A time following a date, where the date has already made the context unambiguous.
_TIME_OF_DAY: Final[str] = rf"{_CLOCK}{_SECONDS}?{_MERIDIEM}?{_ZONE}?"
#: A time with nothing else to identify it, so seconds or a meridiem are required.
_STANDALONE_TIME: Final[str] = rf"{_CLOCK}(?:{_SECONDS}{_MERIDIEM}?|{_MERIDIEM}){_ZONE}?"
#: A date written with digits alone, in whichever order the fields come.
_NUMERIC_DATE: Final[str] = r"\d{1,4}[/-]\d{1,2}[/-]\d{2,4}"
#: A date in ISO 8601 order.
_ISO_DATE: Final[str] = rf"{_YEAR}-\d{{2}}-\d{{2}}"

#: The timestamp formats recognised, longest first so that a date keeps the time that follows it.
_PATTERNS: Final[tuple[str, ...]] = (
	# Wed Sep  2 22:11:03 2026: C's ctime, and the Unix date command.
	rf"{_DAY_NAME}[ \t]+{_MONTH_NAME}[ \t]+{_DAY}[ \t]+{_TIME_OF_DAY}[ \t]+{_YEAR}",
	# Wed, 02 Sep 2026 22:11:03 GMT: RFC 2822, HTTP headers and Windows event logs.
	rf"{_DAY_NAME},?[ \t]+{_DAY}[ \t]+{_MONTH_NAME}[ \t]+{_YEAR}(?:,?[ \t]+{_TIME_OF_DAY})?",
	# 02/Sep/2026:22:11:03 +0200: the common log format of Apache and IIS.
	rf"{_DAY}/{_MONTH_NAME}/{_YEAR}:{_TIME_OF_DAY}",
	# Sep  2 22:11:03: syslog and journalctl, and the date column of ls and dir.
	rf"{_MONTH_NAME}[ \t]+{_DAY}[ \t]+{_TIME_OF_DAY}",
	# Sep 2, 2026 and 2 Sep 2026, with or without a time.
	rf"{_MONTH_NAME}[ \t]+{_DAY},?[ \t]+{_YEAR}(?:,?[ \t]+{_TIME_OF_DAY})?",
	rf"{_DAY}[ \t]+{_MONTH_NAME}[ \t]+{_YEAR}(?:,?[ \t]+{_TIME_OF_DAY})?",
	# 2026-09-02T22:11:03.123Z: ISO 8601, and what the Python and Java logging defaults produce.
	rf"{_ISO_DATE}(?:[T \t]{_TIME_OF_DAY})?",
	# 09/02/2026 10:11:03 PM: Windows, and 2026/09/02 22:11:03 from Go's log package.
	rf"{_NUMERIC_DATE}(?:,?[ \t]+{_TIME_OF_DAY})?",
	# 22:11:03,123 on its own.
	_STANDALONE_TIME,
)

#: The bracket pairs a timestamp is commonly wrapped in, which are removed along with it.
_BRACKETS: Final[tuple[tuple[str, str], ...]] = ((r"\[", r"\]"), (r"\(", r"\)"), ("<", ">"))

#: Kernel ring buffer timestamps, as printed by ``dmesg``. Seconds since boot rather than a time of
#: day, and recognised only inside its brackets, because bare ``0.123456`` is just a number.
_UPTIME: Final[str] = r"\[[ \t]*\d+\.\d{6}\][ \t]*"

#: Rejects a timestamp that is part of a longer word, number or path, such as the date in
#: ``build-2026-09-02.log``, while still allowing one that ends a sentence.
_LEFT_GUARD: Final[str] = r"(?<![\w/.-])"
_RIGHT_GUARD: Final[str] = r"(?![\w/-])(?!\.\w)"


def _buildPattern() -> str:
	"""Assemble the expression matching one timestamp together with the space around it.

	Taking the surrounding horizontal whitespace into the match, and putting a single space back in
	its place, closes the gap a removed timestamp leaves behind without disturbing the alignment of
	the rest of the line.

	:return: The complete regular expression source.
	"""
	core = "|".join(_PATTERNS)
	# The bracketed forms come first so that a wrapped timestamp takes its brackets with it, rather
	# than leaving an empty pair behind.
	wrapped = [rf"{opening}[ \t]*(?:{core})[ \t]*{closing}" for opening, closing in _BRACKETS]
	wrapped.append(core)
	alternatives = "|".join(wrapped)
	return rf"{_UPTIME}|[ \t]*{_LEFT_GUARD}(?:{alternatives}){_RIGHT_GUARD}[ \t]*"


#: Matches a single timestamp anywhere in a line.
_TIMESTAMP_RE: Final[re.Pattern[str]] = re.compile(_buildPattern(), re.IGNORECASE)

#: The punctuation left dangling at the start of a line once its leading timestamp has gone, as in
#: ``2026-09-02 22:11:03 - INFO - ready``. A longer run, such as the ``---`` of a banner line, is
#: left in place because it is part of the message rather than a separator.
_LEADING_SEPARATOR_RE: Final[re.Pattern[str]] = re.compile(r"^[-–—|:>]{1,2}[ \t]+")


def stripFromLine(line: str) -> str:
	"""Remove every date and time recognised in one line.

	:param line: A captured terminal line.
	:return: The line without its timestamps, or the line itself if it held none.
	"""
	if not any(character.isdigit() for character in line):
		return line
	indent = line[: len(line) - len(line.lstrip())]
	body = line[len(indent) :]
	stripped = _TIMESTAMP_RE.sub(" ", body)
	if stripped == body:
		return line
	if _TIMESTAMP_RE.match(body):
		stripped = _LEADING_SEPARATOR_RE.sub("", stripped.lstrip(), count=1)
	stripped = stripped.strip()
	# The line's own indentation is restored, so that indented output keeps its shape.
	return indent + stripped if stripped else ""


def stripFromLines(lines: list[str]) -> list[str]:
	"""Remove every date and time recognised in a snapshot.

	A line that held nothing but a timestamp is dropped rather than left blank, because it carried
	no message to keep. Lines that were already blank are untouched, so that whether they survive
	remains the business of the ``keepBlankLines`` setting alone.

	:param lines: The captured lines.
	:return: The lines without their timestamps.
	"""
	result: list[str] = []
	for line in lines:
		stripped = stripFromLine(line)
		if stripped or not line.strip():
			result.append(stripped)
	return result
