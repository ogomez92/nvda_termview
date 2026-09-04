"""Configuration specification for termview.

Only simple scalars live in ``config.conf``; the keyword list is stored separately by
:mod:`.keywords`, because ConfigObj cannot round trip arbitrary user text reliably.
"""

from typing import Any, Final

import config

#: The section termview's settings occupy within NVDA's configuration.
CONFIG_SECTION: Final[str] = "termview"

#: The configuration specification registered with NVDA.
CONFIG_SPEC: Final[dict[str, str]] = {
	"includeScrollback": "boolean(default=True)",
	"keepBlankLines": "boolean(default=True)",
	"stripTimestamps": "boolean(default=True)",
	"showLineNumbers": "boolean(default=False)",
	"maxLines": "integer(default=0, min=0, max=100000)",
}


def initialize() -> None:
	"""Register termview's configuration specification with NVDA."""
	config.conf.spec[CONFIG_SECTION] = CONFIG_SPEC


def getConf() -> Any:
	"""Return termview's section of NVDA's configuration."""
	return config.conf[CONFIG_SECTION]
