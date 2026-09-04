"""Keyword definitions and matching for termview.

A keyword marks a terminal line as a heading in the generated snapshot.
Matching is always case insensitive, as documented for this add-on.
"""

import json
import os
import re
from enum import IntEnum, unique
from collections.abc import Iterable, Iterator
from typing import Any, Final

import addonHandler
import NVDAState
from logHandler import log

addonHandler.initTranslation()


#: Name of the JSON file holding the keyword list, stored in NVDA's configuration folder.
#: A separate file is used rather than ``config.conf`` because ConfigObj cannot round trip
#: values containing both single and double quotes, which arbitrary user patterns may.
KEYWORDS_FILE_NAME: Final[str] = "termview-keywords.json"

#: The lowest (most prominent) heading level a keyword may be given.
MIN_HEADING_LEVEL: Final[int] = 1
#: The highest (least prominent) heading level a keyword may be given.
MAX_HEADING_LEVEL: Final[int] = 6


@unique
class MatchType(IntEnum):
	"""How a keyword's pattern is matched against a terminal line."""

	ANYWHERE = 0
	"""The pattern matches anywhere within the line."""
	WHOLE_WORD = 1
	"""The pattern matches only when surrounded by word boundaries."""
	WILDCARD = 2
	"""``*`` matches any run of characters and ``?`` matches any single character."""
	REGEXP = 3
	"""The pattern is a Python regular expression."""


#: User visible labels for each match type, in the order they are offered in the GUI.
MATCH_TYPE_LABELS: Final[dict[MatchType, str]] = {
	# Translators: A keyword match type in the termview settings, matching anywhere in a line.
	MatchType.ANYWHERE: _("Anywhere in the line"),
	# Translators: A keyword match type in the termview settings, matching a whole word only.
	MatchType.WHOLE_WORD: _("Whole word only"),
	# Translators: A keyword match type in the termview settings,
	# where * matches any text and ? matches any single character.
	MatchType.WILDCARD: _("Wildcard (* and ?)"),
	# Translators: A keyword match type in the termview settings, matching a regular expression.
	MatchType.REGEXP: _("Regular expression"),
}


def _translateWildcard(pattern: str) -> str:
	"""Convert a shell style wildcard pattern into a regular expression fragment.

	Unlike :func:`fnmatch.translate`, the result is not anchored, so it can be searched for
	anywhere within a line and can be wrapped in word boundaries.

	:param pattern: The wildcard pattern, where ``*`` matches any run of characters
		and ``?`` matches exactly one character.
	:return: An unanchored regular expression fragment.
	"""
	parts: list[str] = []
	for char in pattern:
		if char == "*":
			parts.append(".*")
		elif char == "?":
			parts.append(".")
		else:
			parts.append(re.escape(char))
	return "".join(parts)


class Keyword:
	"""A single keyword rule: a pattern, how to match it, and the heading level to apply."""

	__slots__ = ("pattern", "matchType", "level", "enabled", "_regexp")

	def __init__(
		self,
		pattern: str,
		matchType: MatchType = MatchType.ANYWHERE,
		level: int = 2,
		enabled: bool = True,
	) -> None:
		"""
		:param pattern: The text to look for in a terminal line.
		:param matchType: How ``pattern`` should be interpreted.
		:param level: The HTML heading level (1 to 6) applied to matching lines.
		:param enabled: Whether this keyword takes part in matching.
		:raises re.error: If the pattern cannot be compiled.
		"""
		self.pattern = pattern
		self.matchType = MatchType(matchType)
		self.level = max(MIN_HEADING_LEVEL, min(MAX_HEADING_LEVEL, int(level)))
		self.enabled = bool(enabled)
		self._regexp = self._compile()

	def _compile(self) -> re.Pattern[str]:
		"""Build the case insensitive regular expression implementing this keyword."""
		match self.matchType:
			case MatchType.REGEXP:
				source = self.pattern
			case MatchType.WILDCARD:
				source = _translateWildcard(self.pattern)
			case MatchType.WHOLE_WORD:
				source = rf"\b{re.escape(self.pattern)}\b"
			case _:
				source = re.escape(self.pattern)
		# Keywords are matched case insensitively by design; see the add-on documentation.
		return re.compile(source, re.IGNORECASE)

	def matches(self, line: str) -> bool:
		"""Report whether the given terminal line should be marked as a heading by this keyword.

		:param line: A single line of captured terminal text.
		:return: ``True`` if the line matches and this keyword is enabled.
		"""
		if not self.enabled or not self.pattern:
			return False
		try:
			return self._regexp.search(line) is not None
		except re.error:
			# Catastrophic backtracking or a similar runtime regexp failure: never break a snapshot.
			log.debugWarning(f"termview: keyword {self.pattern!r} failed to match", exc_info=True)
			return False

	def toDict(self) -> dict[str, Any]:
		"""Serialise this keyword for storage."""
		return {
			"pattern": self.pattern,
			"matchType": int(self.matchType),
			"level": self.level,
			"enabled": self.enabled,
		}

	@classmethod
	def fromDict(cls, data: dict[str, Any]) -> "Keyword":
		"""Recreate a keyword from its serialised form.

		:param data: A mapping as produced by :meth:`toDict`.
		:raises re.error: If the stored pattern no longer compiles.
		"""
		try:
			matchType = MatchType(int(data.get("matchType", MatchType.ANYWHERE)))
		except ValueError:
			matchType = MatchType.ANYWHERE
		return cls(
			pattern=str(data.get("pattern", "")),
			matchType=matchType,
			level=int(data.get("level", 2)),
			enabled=bool(data.get("enabled", True)),
		)

	def copy(self) -> "Keyword":
		"""Return an independent copy of this keyword."""
		return Keyword(self.pattern, self.matchType, self.level, self.enabled)

	def __repr__(self) -> str:
		return (
			f"Keyword(pattern={self.pattern!r}, matchType={self.matchType!r}, "
			f"level={self.level!r}, enabled={self.enabled!r})"
		)


class KeywordList:
	"""An ordered collection of :class:`Keyword` rules, with persistence and matching."""

	def __init__(self, keywords: Iterable[Keyword] | None = None) -> None:
		self._keywords: list[Keyword] = list(keywords) if keywords is not None else []

	def __iter__(self) -> Iterator[Keyword]:
		return iter(self._keywords)

	def __len__(self) -> int:
		return len(self._keywords)

	def __getitem__(self, index: int) -> Keyword:
		return self._keywords[index]

	def __setitem__(self, index: int, keyword: Keyword) -> None:
		self._keywords[index] = keyword

	def append(self, keyword: Keyword) -> None:
		"""Add a keyword to the end of the list."""
		self._keywords.append(keyword)

	def remove(self, index: int) -> None:
		"""Remove the keyword at the given index."""
		del self._keywords[index]

	def clear(self) -> None:
		"""Remove every keyword."""
		self._keywords.clear()

	def copy(self) -> "KeywordList":
		"""Return a deep copy, suitable for editing in a dialog before saving."""
		return KeywordList(keyword.copy() for keyword in self._keywords)

	def headingLevelFor(self, line: str) -> int | None:
		"""Determine the heading level a line should be given.

		When several keywords match the same line, the most prominent (numerically lowest)
		heading level wins; ties are broken by the order of the list.

		:param line: A single line of captured terminal text.
		:return: A heading level between 1 and 6, or ``None`` if no keyword matched.
		"""
		best: int | None = None
		for keyword in self._keywords:
			if keyword.matches(line) and (best is None or keyword.level < best):
				best = keyword.level
				if best == MIN_HEADING_LEVEL:
					# No keyword can be more prominent, so stop early.
					break
		return best

	@staticmethod
	def _filePath() -> str:
		"""The absolute path of the file the keyword list is stored in."""
		return os.path.join(NVDAState.WritePaths.configDir, KEYWORDS_FILE_NAME)

	@classmethod
	def load(cls) -> "KeywordList":
		"""Load the keyword list from NVDA's configuration folder.

		A missing or unreadable file yields the default keyword list rather than an error,
		so a corrupt file can never stop the add-on from loading.
		"""
		path = cls._filePath()
		if not os.path.isfile(path):
			return cls.makeDefault()
		try:
			with open(path, "r", encoding="utf-8") as f:
				raw = json.load(f)
		except (OSError, ValueError):
			log.error(f"termview: could not read keywords from {path}", exc_info=True)
			return cls.makeDefault()
		if not isinstance(raw, list):
			log.error(f"termview: {path} does not hold a list of keywords")
			return cls.makeDefault()
		keywords: list[Keyword] = []
		for entry in raw:
			if not isinstance(entry, dict):
				continue
			try:
				keywords.append(Keyword.fromDict(entry))
			except (re.error, TypeError, ValueError):
				log.error(f"termview: discarding invalid keyword {entry!r}", exc_info=True)
		return cls(keywords)

	def save(self) -> bool:
		"""Write the keyword list to NVDA's configuration folder.

		:return: ``True`` if the list was written successfully.
		"""
		path = self._filePath()
		try:
			with open(path, "w", encoding="utf-8") as f:
				json.dump([keyword.toDict() for keyword in self._keywords], f, indent="\t")
		except OSError:
			log.error(f"termview: could not write keywords to {path}", exc_info=True)
			return False
		return True

	@classmethod
	def makeDefault(cls) -> "KeywordList":
		"""Build the keyword list offered the first time the add-on is used.

		The defaults cover the words that most often mark an interesting line of terminal output.
		"""
		return cls(
			[
				# Translators: A default termview keyword, matching lines reporting an error.
				Keyword(_("error"), MatchType.ANYWHERE, 2),
				# Translators: A default termview keyword, matching lines reporting a failure.
				Keyword(_("failed"), MatchType.ANYWHERE, 2),
				# Translators: A default termview keyword, matching lines reporting a warning.
				Keyword(_("warning"), MatchType.ANYWHERE, 3),
			],
		)
