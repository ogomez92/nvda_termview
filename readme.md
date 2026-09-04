# Termview

Termview takes a snapshot of a terminal and opens it in a review window you can read with browse mode.

Terminals are awkward to read with a screen reader. Output scrolls past while you are still listening to it, review mode only reaches what is currently on screen, and finding the one line that says why a build failed means arrowing through hundreds of lines. Termview copies the terminal's contents into a browse mode window, where all of browse mode is available: arrow keys, `f` for find, say all, and quick navigation. Lines that contain a keyword you have configured become headings, so pressing `h`, or opening the elements list with `NVDA+f7`, jumps straight to the errors.

The snapshot is a still picture. It does not update as the terminal produces more output; press the command again for a fresh one.

## Commands

| Command | Default gesture | Description |
|---|---|---|
| Review terminal | `NVDA+shift+v` | Takes a snapshot of the terminal you are on and opens it in the review window. |
| Open Termview settings | none | Opens NVDA's settings at the Termview category. |

Both gestures can be changed in NVDA's Input gestures dialog, under the Termview category.

## Reading a snapshot

The review window opens in browse mode, so all the usual keys work:

* `h` and `shift+h` move between headings; `1` to `6` move between headings of that level.
* `NVDA+f7` opens the elements list, which lists every heading in the snapshot.
* `NVDA+downArrow` reads the whole snapshot from the cursor.
* `control+f` finds text, and `f3` finds the next match.
* `control+shift+c`, or the Copy button, copies the whole snapshot to the clipboard.
* `escape`, or the Close button, closes the window.

The window opens with the Copy and Close buttons, then a separator, then the snapshot, so the buttons are reached straight away rather than at the end of a document thousands of lines long. The snapshot itself starts with a short summary: which terminal it came from, when it was taken, and how many lines and headings it contains.

## Keywords

Keywords are managed in NVDA's settings, under the Termview category. Each keyword has:

* **Keyword** — the text to look for.
* **Match** — how the text is matched (see below).
* **Heading level** — 1 to 6. Level 1 is the most prominent.
* **Enabled** — clear this to set a keyword aside without deleting it.

Keywords are always matched **without regard to case**, so `error` also finds `Error` and `ERROR`.

### Match types

| Match | Meaning | Example |
|---|---|---|
| Anywhere in the line | The text appears anywhere, even inside a longer word. | `error` matches `terrorist` and `ERROR:` |
| Whole word only | The text appears as a complete word. | `error` matches `an error occurred` but not `terrorist` |
| Wildcard (`*` and `?`) | `*` stands for any run of characters and `?` for a single character. | `test*failed` matches `test_login ... FAILED` |
| Regular expression | A Python regular expression. | `^\s*\d+ passed` matches `  12 passed` |

When more than one keyword matches the same line, the most prominent heading level wins. If `error` is level 2 and `fatal` is level 1, a line saying `fatal error` becomes a level 1 heading.

Termview starts with three keywords — `error`, `failed` and `warning` — which you can change or replace. The **Restore defaults** button brings them back.

Keywords are stored in `termview-keywords.json` in your NVDA configuration folder, so they survive NVDA updates and can be copied between machines.

## Snapshot options

These are in the Snapshot group of the Termview settings.

* **Include text that has scrolled off the screen** (on by default). When on, Termview captures the whole buffer, including the scrollback. When off, it captures only what is currently on screen, which is faster on terminals with a very large history.
* **Keep blank lines** (on by default). When off, blank lines are dropped, which makes a sparse log much shorter to read.
* **Strip dates and times** (on by default). Takes the timestamps out of the snapshot, so each line is read as its message rather than its clock. Termview recognises the usual Windows, Unix and logging library formats: ISO 8601 (`2026-09-02T22:11:03.123Z`), the Python, Java and Go logging defaults, syslog and `journalctl` (`Sep  2 22:11:03`), the Apache and IIS common log format, `dmesg` uptimes, the date column of `ls` and `dir`, and times on their own such as `[22:11:03]`, in brackets or not. A line that held nothing but a timestamp is left out altogether. Anything that only looks like a time is kept: `1:30` on its own, version numbers such as `1.2.34`, IP addresses, and dates that are part of a longer word or path, as in `build-2026-09-02.log`. The terminal itself is untouched, so the timestamps are still there if you take another snapshot with this cleared.
* **Show line numbers** (off by default). Prefixes each line with its position in the snapshot, which helps when comparing the snapshot with the terminal itself.
* **Maximum number of lines** (0 by default, meaning no limit). When set, only the most recent lines are kept and the summary says that older lines were omitted.

## Supported terminals

Termview reads whatever NVDA itself can read, so it works with:

* Windows Console Host (`cmd.exe`, Windows PowerShell), including the full screen buffer.
* Windows Terminal, PowerShell 7 and WSL, including the scrollback.
* Terminals NVDA reads through its display model, such as PuTTY and mintty, for the text currently on screen.

If you press the command somewhere that is not a terminal, Termview says "Not a terminal window" and does nothing.

## Why it does not disturb the terminal

Some tools that read consoles attach NVDA's own process to the console with `AttachConsole`. NVDA does that itself to read a legacy console, so a second caller detaches NVDA from the console it was reading, and the terminal stops speaking until NVDA is restarted.

Termview never does that. It reads a legacy console through the handle NVDA already holds, reads UI Automation terminals through the text pattern the object already exposes, and never moves the caret, the review cursor or the navigator object, nor patches any NVDA class. As a further safety net, after each snapshot it checks that the terminal resumed reporting new output once you return to it, and restarts monitoring only in the unlikely event that it did not.

## Building from source

See `docs/BUILDING.md` in the source repository for the full add-on template instructions. In short:

```
uv sync
uv run scons
```

This produces `termview-<version>.nvda-addon`. `uv run scons pot` generates the translation template.

The add-on itself needs nothing beyond NVDA and the Python standard library. If a runtime dependency is ever added, it is declared in `pyproject.toml` and installed by `uv sync` into `.venv\Lib\site-packages` inside the add-on directory, which `addon/globalPlugins/termview/__init__.py` adds to `sys.path` around its imports and removes again immediately, so that it cannot shadow NVDA's own modules or those of another add-on.

Python is pinned to 3.13.13 in `.python-version`, matching the interpreter NVDA 2026 ships.

## License

Copyright (C) 2026 Termview contributors.

This add-on is distributed under the terms of the GNU General Public License, version 2 or later. See the file COPYING.txt for further details.
