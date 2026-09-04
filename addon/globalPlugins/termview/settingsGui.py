"""The termview settings category and its keyword editor."""

import re

import addonHandler
import gui
import gui.contextHelp
import wx
from gui import guiHelper, nvdaControls
from gui.settingsDialogs import SettingsPanel
from logHandler import log

from .conf import getConf
from .keywords import (
	MATCH_TYPE_LABELS,
	MAX_HEADING_LEVEL,
	MIN_HEADING_LEVEL,
	Keyword,
	KeywordList,
	MatchType,
)

addonHandler.initTranslation()


#: The order in which match types are offered in the keyword dialog.
_MATCH_TYPE_ORDER: tuple[MatchType, ...] = (
	MatchType.ANYWHERE,
	MatchType.WHOLE_WORD,
	MatchType.WILDCARD,
	MatchType.REGEXP,
)


class KeywordEntryDialog(
	gui.contextHelp.ContextHelpMixin,
	wx.Dialog,  # wxPython does not seem to call base class initializer, put last in MRO
):
	"""A dialog for adding or editing a single keyword."""

	def __init__(self, parent: wx.Window, title: str, keyword: Keyword | None = None) -> None:
		"""
		:param parent: The dialog's parent window.
		:param title: The dialog title.
		:param keyword: The keyword to edit, or ``None`` to create a new one.
		"""
		super().__init__(parent, title=title)
		#: The keyword built when the dialog is accepted.
		self.keyword: Keyword | None = None

		mainSizer = wx.BoxSizer(wx.VERTICAL)
		sHelper = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

		self.patternTextCtrl = sHelper.addLabeledControl(
			# Translators: The label of an edit field in the termview keyword dialog.
			_("&Keyword"),
			wx.TextCtrl,
		)

		self.typeRadioBox = sHelper.addItem(
			wx.RadioBox(
				self,
				# Translators: The label of a group of radio buttons in the termview keyword dialog,
				# choosing how the keyword is matched against a line.
				label=_("&Match"),
				choices=[MATCH_TYPE_LABELS[matchType] for matchType in _MATCH_TYPE_ORDER],
				style=wx.RA_SPECIFY_ROWS,
			),
		)

		self.levelSpinCtrl = sHelper.addLabeledControl(
			# Translators: The label of a spin control in the termview keyword dialog,
			# choosing the heading level given to lines containing the keyword.
			_("Heading &level"),
			nvdaControls.SelectOnFocusSpinCtrl,
			min=MIN_HEADING_LEVEL,
			max=MAX_HEADING_LEVEL,
			initial=2,
		)

		self.enabledCheckBox = sHelper.addItem(
			# Translators: The label of a check box in the termview keyword dialog.
			wx.CheckBox(self, label=_("&Enabled")),
		)
		self.enabledCheckBox.SetValue(True)

		sHelper.addDialogDismissButtons(wx.OK | wx.CANCEL, separated=True)
		mainSizer.Add(sHelper.sizer, border=guiHelper.BORDER_FOR_DIALOGS, flag=wx.ALL)
		mainSizer.Fit(self)
		self.SetSizer(mainSizer)
		self.CentreOnParent()

		if keyword is not None:
			self.patternTextCtrl.SetValue(keyword.pattern)
			self.typeRadioBox.SetSelection(_MATCH_TYPE_ORDER.index(keyword.matchType))
			self.levelSpinCtrl.SetValue(keyword.level)
			self.enabledCheckBox.SetValue(keyword.enabled)
		else:
			self.typeRadioBox.SetSelection(_MATCH_TYPE_ORDER.index(MatchType.ANYWHERE))

		self.patternTextCtrl.SetFocus()
		self.Bind(wx.EVT_BUTTON, self.onOk, id=wx.ID_OK)

	def _getMatchType(self) -> MatchType:
		"""The match type currently selected in the dialog."""
		selection = self.typeRadioBox.GetSelection()
		if selection == wx.NOT_FOUND:
			return MatchType.ANYWHERE
		return _MATCH_TYPE_ORDER[selection]

	def onOk(self, evt: wx.CommandEvent) -> None:
		"""Validate the entry and build the keyword, or explain why it cannot be accepted."""
		pattern = self.patternTextCtrl.GetValue()
		if not pattern:
			gui.messageBox(
				# Translators: An error shown when the keyword field was left empty.
				_("A keyword is required."),
				# Translators: The title of an error shown by the termview keyword dialog.
				_("Keyword error"),
				wx.OK | wx.ICON_WARNING,
				self,
			)
			self.patternTextCtrl.SetFocus()
			return
		try:
			self.keyword = Keyword(
				pattern=pattern,
				matchType=self._getMatchType(),
				level=self.levelSpinCtrl.GetValue(),
				enabled=self.enabledCheckBox.GetValue(),
			)
		except re.error as e:
			log.debugWarning(f"termview: invalid keyword pattern {pattern!r}: {e}")
			gui.messageBox(
				# Translators: An error shown when a keyword's regular expression is invalid.
				# {error} is the message describing what is wrong with it.
				_('Regular expression error in the keyword field: "{error}".').format(error=e),
				# Translators: The title of an error shown by the termview keyword dialog.
				_("Keyword error"),
				wx.OK | wx.ICON_WARNING,
				self,
			)
			self.patternTextCtrl.SetFocus()
			return
		evt.Skip()


class TermviewSettingsPanel(SettingsPanel):
	"""The termview category in NVDA's settings."""

	# Translators: The label of the termview category in NVDA's settings.
	title = _("Termview")

	panelDescription = _(
		# Translators: A description shown at the top of the termview settings category.
		"Lines of a terminal snapshot that contain one of these keywords become headings, so they can be reached with browse mode heading navigation and the elements list. Keywords are matched without regard to case. When several keywords match the same line, the most prominent heading level is used.",
	)

	def makeSettings(self, settingsSizer: wx.BoxSizer) -> None:
		"""Populate the settings category.

		:param settingsSizer: The sizer the controls are added to.
		"""
		#: The keywords being edited; only written to disk when the dialog is accepted.
		self._keywords = KeywordList.load()

		sHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
		sHelper.addItem(wx.StaticText(self, label=self.panelDescription))

		self.keywordList = sHelper.addLabeledControl(
			# Translators: The label of the list of keywords in the termview settings.
			_("&Keywords"),
			wx.ListCtrl,
			style=wx.LC_REPORT | wx.LC_SINGLE_SEL,
		)
		# Translators: The label of a column listing the text each termview keyword looks for.
		self.keywordList.AppendColumn(_("Keyword"), width=180)
		# Translators: The label of a column listing how each termview keyword is matched.
		self.keywordList.AppendColumn(_("Match"), width=150)
		# Translators: The label of a column listing the heading level each termview keyword applies.
		self.keywordList.AppendColumn(_("Level"), width=60)
		# Translators: The label of a column listing whether each termview keyword is in use.
		self.keywordList.AppendColumn(_("Enabled"), width=70)
		self._refreshList()

		bHelper = guiHelper.ButtonHelper(orientation=wx.HORIZONTAL)
		bHelper.addButton(
			parent=self,
			# Translators: The label of a button in the termview settings, to add a keyword.
			label=_("&Add..."),
		).Bind(wx.EVT_BUTTON, self.onAddClick)
		self.editButton = bHelper.addButton(
			parent=self,
			# Translators: The label of a button in the termview settings, to change a keyword.
			label=_("&Edit..."),
		)
		self.editButton.Bind(wx.EVT_BUTTON, self.onEditClick)
		self.removeButton = bHelper.addButton(
			parent=self,
			# Translators: The label of a button in the termview settings, to delete a keyword.
			label=_("&Remove"),
		)
		self.removeButton.Bind(wx.EVT_BUTTON, self.onRemoveClick)
		bHelper.sizer.AddStretchSpacer()
		bHelper.addButton(
			parent=self,
			# Translators: The label of a button in the termview settings, restoring the
			# keywords the add-on suggests out of the box.
			label=_("Restore &defaults"),
		).Bind(wx.EVT_BUTTON, self.onRestoreDefaultsClick)
		sHelper.addItem(bHelper, flag=wx.EXPAND)

		# Translators: The label of a group of options in the termview settings,
		# controlling what a snapshot contains.
		snapshotSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Snapshot"))
		snapshotBox = snapshotSizer.GetStaticBox()
		snapshotHelper = guiHelper.BoxSizerHelper(self, sizer=snapshotSizer)
		conf = getConf()

		self.scrollbackCheckBox = snapshotHelper.addItem(
			wx.CheckBox(
				snapshotBox,
				# Translators: The label of a check box in the termview settings. When cleared,
				# only the text currently on screen is captured.
				label=_("Include text that has &scrolled off the screen"),
			),
		)
		self.scrollbackCheckBox.SetValue(conf["includeScrollback"])

		self.blankLinesCheckBox = snapshotHelper.addItem(
			wx.CheckBox(
				snapshotBox,
				# Translators: The label of a check box in the termview settings.
				label=_("Keep &blank lines"),
			),
		)
		self.blankLinesCheckBox.SetValue(conf["keepBlankLines"])

		self.stripTimestampsCheckBox = snapshotHelper.addItem(
			wx.CheckBox(
				snapshotBox,
				# Translators: The label of a check box in the termview settings. When checked, the
				# dates and times most logs put on every line are left out of the snapshot.
				label=_("Strip dates and &times"),
			),
		)
		self.stripTimestampsCheckBox.SetValue(conf["stripTimestamps"])

		self.lineNumbersCheckBox = snapshotHelper.addItem(
			wx.CheckBox(
				snapshotBox,
				# Translators: The label of a check box in the termview settings.
				label=_("Show line &numbers"),
			),
		)
		self.lineNumbersCheckBox.SetValue(conf["showLineNumbers"])

		self.maxLinesSpinCtrl = snapshotHelper.addLabeledControl(
			# Translators: The label of a spin control in the termview settings, limiting how many
			# lines a snapshot holds. Zero means there is no limit.
			_("&Maximum number of lines (0 for no limit)"),
			nvdaControls.SelectOnFocusSpinCtrl,
			min=0,
			max=100000,
			initial=conf["maxLines"],
		)
		sHelper.addItem(snapshotSizer)

		self.keywordList.Bind(wx.EVT_LIST_ITEM_SELECTED, self.onListSelectionChange)
		self.keywordList.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.onListSelectionChange)
		self.keywordList.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.onEditClick)
		self._updateButtonStates()

	def _refreshList(self, selectIndex: int | None = None) -> None:
		"""Rebuild the keyword list control from the keywords being edited.

		:param selectIndex: The index to select afterwards, if it still exists.
		"""
		self.keywordList.DeleteAllItems()
		# Translators: Shown in the termview keyword list for a keyword that is in use.
		yes = _("yes")
		# Translators: Shown in the termview keyword list for a keyword that is not in use.
		no = _("no")
		for keyword in self._keywords:
			self.keywordList.Append(
				(
					keyword.pattern,
					MATCH_TYPE_LABELS[keyword.matchType],
					str(keyword.level),
					yes if keyword.enabled else no,
				),
			)
		if selectIndex is not None and 0 <= selectIndex < self.keywordList.GetItemCount():
			self.keywordList.Select(selectIndex)
			self.keywordList.Focus(selectIndex)

	def _selectedIndex(self) -> int:
		"""The index of the selected keyword, or ``-1`` if nothing is selected."""
		return self.keywordList.GetFirstSelected()

	def _updateButtonStates(self) -> None:
		"""Enable the buttons that act on a keyword only while one is selected."""
		hasSelection = self._selectedIndex() >= 0
		self.editButton.Enable(hasSelection)
		self.removeButton.Enable(hasSelection)

	def onListSelectionChange(self, evt: wx.ListEvent) -> None:
		"""Keep the buttons in step with the list selection."""
		evt.Skip()
		self._updateButtonStates()

	def onAddClick(self, evt: wx.CommandEvent) -> None:
		"""Add a new keyword."""
		# Translators: The title of the dialog for adding a termview keyword.
		entryDialog = KeywordEntryDialog(self, title=_("Add keyword"))
		if entryDialog.ShowModal() == wx.ID_OK and entryDialog.keyword is not None:
			self._keywords.append(entryDialog.keyword)
			self._refreshList(selectIndex=len(self._keywords) - 1)
			self.keywordList.SetFocus()
			self._updateButtonStates()
		entryDialog.Destroy()

	def onEditClick(self, evt: wx.CommandEvent) -> None:
		"""Change the selected keyword."""
		index = self._selectedIndex()
		if index < 0:
			return
		entryDialog = KeywordEntryDialog(
			self,
			# Translators: The title of the dialog for changing a termview keyword.
			title=_("Edit keyword"),
			keyword=self._keywords[index],
		)
		if entryDialog.ShowModal() == wx.ID_OK and entryDialog.keyword is not None:
			self._keywords[index] = entryDialog.keyword
			self._refreshList(selectIndex=index)
			self.keywordList.SetFocus()
		entryDialog.Destroy()

	def onRemoveClick(self, evt: wx.CommandEvent) -> None:
		"""Delete the selected keyword."""
		index = self._selectedIndex()
		if index < 0:
			return
		self._keywords.remove(index)
		self._refreshList(selectIndex=min(index, len(self._keywords) - 1))
		self.keywordList.SetFocus()
		self._updateButtonStates()

	def onRestoreDefaultsClick(self, evt: wx.CommandEvent) -> None:
		"""Replace the keyword list with the add-on's suggested keywords."""
		if (
			gui.messageBox(
				# Translators: A confirmation shown before replacing all termview keywords.
				_("Replace the current keywords with the default ones?"),
				# Translators: The title of a confirmation shown by the termview settings.
				_("Restore defaults"),
				wx.YES | wx.NO | wx.ICON_QUESTION,
				self,
			)
			!= wx.YES
		):
			return
		self._keywords = KeywordList.makeDefault()
		self._refreshList(selectIndex=0)
		self.keywordList.SetFocus()
		self._updateButtonStates()

	def onSave(self) -> None:
		"""Store the settings when the parent dialog is accepted."""
		conf = getConf()
		conf["includeScrollback"] = self.scrollbackCheckBox.GetValue()
		conf["keepBlankLines"] = self.blankLinesCheckBox.GetValue()
		conf["stripTimestamps"] = self.stripTimestampsCheckBox.GetValue()
		conf["showLineNumbers"] = self.lineNumbersCheckBox.GetValue()
		conf["maxLines"] = self.maxLinesSpinCtrl.GetValue()
		if not self._keywords.save():
			gui.messageBox(
				# Translators: An error shown when the keyword list could not be saved to disk.
				_("The keywords could not be saved. See NVDA's log for details."),
				# Translators: The title of an error shown by the termview settings.
				_("Termview error"),
				wx.OK | wx.ICON_ERROR,
				self,
			)
