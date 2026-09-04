## 1.0.0

First release.

* Adds the Review terminal command, bound to `NVDA+shift+v` by default, which takes a snapshot of the
  current terminal and opens it in a browse mode review window.
* Adds a Termview category to NVDA's settings for managing keywords. Lines containing a keyword become
  headings at a level you choose per keyword, matched anywhere, as a whole word, with `*` and `?`
  wildcards, or with a regular expression, always without regard to case.
* Strips dates and times from the snapshot by default, so a log is read as its messages rather than
  its clock. Turn off Strip dates and times in the Termview settings to keep them.
* Captures the full scrollback of Windows Console Host, Windows Terminal and WSL, and the visible screen
  of other terminals, without ever changing which console NVDA's own process is attached to.
