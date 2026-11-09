import QtQuick
import QtCore as Core
import QtQuick.Controls as Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "ShortcutKeys.js" as ShortcutKeys

BarWidget {
  id: root
  moduleName: "kel.omashortcuts"
  property bool popupOpen: false
  readonly property bool opened: popupOpen
  property var shortcuts: []
  property var existing: []
  property string revision: ""
  property int activeCount: 0
  property string status: ""
  property bool editing: false
  property string editingId: ""
  property string actionType: "command"
  property bool editingEnabled: true
  property bool paused: false
  property bool canUndoDelete: false
  property string transferMode: ""
  property string transferPath: ""
  property var pendingPicker: null
  property string importHash: ""
  property int importAdded: 0
  property int importSkipped: 0
  property string noticeKey: ""
  property string noticeDetail: ""
  property bool recording: false
  onRecordingChanged: if (!recording && editing) changed()
  property string heldModifiers: ""
  property var pressedModifierKeys: []
  property bool unsupportedKey: false
  property string deletingId: ""
  property bool showExisting: false
  readonly property var visibleRows: (showExisting ? existing : shortcuts).filter(function(row) {
    return (row.name + " " + row.shortcut).toLowerCase().indexOf(filter.text.toLowerCase()) >= 0
  })
  property string validatedDraft: ""
  property string validationCanonical: ""
  property var validationConflicts: []
  readonly property string validationMessage: validationConflicts.length
    ? strings.t(editingEnabled ? "conflict" : "disabledConflict").arg(validationConflicts.join("; "))
    : (valid ? strings.t("available").arg(validationCanonical) : "")
  property var currentRequest: ({})
  readonly property bool filePickerRequest: currentRequest.operation === "choose-export"
    || currentRequest.operation === "choose-import"
  property string requestDraft: ""
  readonly property string draft: JSON.stringify({
    id: editingId, name: nameField.text, shortcut: keyField.text, type: actionType, enabled: editingEnabled,
    command: actionType === "command" ? commandField.text : "",
    text: actionType === "text" ? textField.text : ""
  })
  readonly property bool valid: validatedDraft !== "" && validatedDraft === draft

  function run(request) {
    if (helper.running) return
    currentRequest = request
    requestDraft = draft
    status = ""
    noticeKey = ""
    noticeDetail = ""
    helper.running = true
  }

  function refresh() { run({ operation: "list" }) }
  function open() {
    if (pendingPicker || (helper.running && filePickerRequest)) return
    popupOpen = true
    refresh()
  }
  function close() { recording = false; popupOpen = false }
  function toggle() { if (popupOpen) close(); else open() }

  function edit(row) {
    recording = false
    editingId = row ? row.id : ""
    actionType = row && row.type === "text" ? "text" : "command"
    editingEnabled = !row || row.enabled !== false
    nameField.text = row ? row.name : ""
    keyField.text = row ? row.shortcut : ""
    commandField.text = row && row.command ? row.command : ""
    textField.text = row && row.type === "text" ? row.text : ""
    editing = true
    deletingId = ""
    changed()
    nameField.forceActiveFocus()
  }

  function chooseFile(importing) {
    transferMode = importing ? "chooseImport" : "chooseExport"
    transferFile.text = Quickshell.env("HOME") + "/OmaHotkeys.json"
    transferFile.forceActiveFocus()
  }

  function reviewTransfer() {
    if (helper.running || !transferFile.text.trim()) return
    transferPath = transferFile.text
    if (transferMode === "chooseImport") run({ operation: "preview-import", path: transferPath })
    else if (transferMode === "chooseExport") transferMode = "export"
  }

  function browseFile() {
    if (helper.running || pendingPicker) return
    var importing = transferMode === "chooseImport"
    pendingPicker = {
      operation: importing ? "choose-import" : "choose-export",
      path: transferFile.text.trim() ? transferFile.text : Quickshell.env("HOME") + "/OmaHotkeys.json",
      title: strings.t(importing ? "importDialogTitle" : "exportDialogTitle"),
      filterLabel: strings.t("jsonFiles")
    }
    popupOpen = false
    if (!popup.backingWindowVisible) startPicker()
  }

  function startPicker() {
    if (!pendingPicker || helper.running || popup.backingWindowVisible) return
    var request = pendingPicker
    pendingPicker = null
    run(request)
  }

  function confirmTransfer() {
    if (helper.running) return
    if (transferMode === "import") {
      run({ operation: "import", path: transferPath, importHash: importHash, revision: revision })
    } else if (transferMode === "export") {
      run({ operation: "export", path: transferPath, confirmed: true, overwrite: true, revision: revision })
    }
  }

  function changed() {
    validatedDraft = ""
    validationCanonical = ""
    validationConflicts = []
    if (editing) validationTimer.restart()
  }

  function validate() {
    if (recording || !editing || !nameField.text.trim() || !keyField.text.trim()) return
    if (actionType === "command" ? !commandField.text.trim() : !textField.text) return
    if (helper.running) { validationTimer.restart(); return }
    var request = JSON.parse(draft)
    request.operation = "validate"
    run(request)
  }

  function save() {
    if (recording || !valid || helper.running) return
    var request = JSON.parse(draft)
    request.operation = "save"
    request.revision = revision
    run(request)
  }

  function finish(code, output, errorOutput) {
    if (filePickerRequest) popupOpen = true
    var response
    try {
      response = JSON.parse(output)
      if (!response || typeof response.ok !== "boolean") throw new Error("Invalid payload")
    } catch (error) {
      status = errorOutput ? errorOutput.slice(0, 1000) : strings.t("invalidResponse")
      console.warn("OmaHotkeys: " + status)
      return
    }
    if (code !== 0 || !response.ok) {
      status = String(response.error || errorOutput || strings.t("failed")).slice(0, 2000)
      validatedDraft = ""
      return
    }
    if (filePickerRequest) {
      if (response.cancelled !== true) {
        if (typeof response.path !== "string" || !response.path) {
          status = strings.t("invalidResponse")
          return
        }
        transferFile.text = response.path
      }
      Qt.callLater(function() { transferFile.forceActiveFocus() })
      return
    }
    if (currentRequest.operation === "validate") {
      if (requestDraft !== draft) { validationTimer.restart(); return }
      if (response.valid) {
        validatedDraft = requestDraft
        validationCanonical = response.canonical
        validationConflicts = response.conflicts || []
      } else {
        validatedDraft = ""
        validationCanonical = ""
        validationConflicts = response.conflicts
      }
      return
    }
    if (currentRequest.operation === "preview-import") {
      if (!Number.isInteger(response.added) || !Number.isInteger(response.skipped)
          || typeof response.importHash !== "string") {
        status = strings.t("invalidResponse")
        return
      }
      importAdded = response.added
      importSkipped = response.skipped
      importHash = response.importHash
      transferMode = "import"
      return
    }
    if (!Array.isArray(response.shortcuts) || !Array.isArray(response.existing)
        || typeof response.revision !== "string" || typeof response.canUndoDelete !== "boolean"
        || (currentRequest.operation === "undo-delete"
          && (typeof response.restoredDisabled !== "boolean" || !Array.isArray(response.undoConflicts)
            || !response.undoConflicts.every(function(value) { return typeof value === "string" })))) {
      status = strings.t("invalidResponse")
      return
    }
    shortcuts = response.shortcuts.slice(0, 200)
    existing = response.existing.slice(0, 2000)
    revision = response.revision
    activeCount = response.activeCount
    paused = response.paused === true
    canUndoDelete = response.canUndoDelete
    if (currentRequest.operation === "save") editing = false
    if (currentRequest.operation === "delete") noticeKey = "deletedUndo"
    if (currentRequest.operation === "undo-delete") {
      noticeKey = response.restoredDisabled ? "undoDisabled" : "undoDone"
      noticeDetail = response.undoConflicts.join("; ").slice(0, 1000)
    }
    if (currentRequest.operation === "import" || currentRequest.operation === "export") {
      noticeKey = currentRequest.operation === "import" ? "importDone" : "exportDone"
      transferMode = ""
    }
    deletingId = ""
    if (editing) changed()
  }

  Commons.Translations { id: strings; directory: Qt.resolvedUrl("i18n") }
  Core.Settings {
    id: preferences
    location: "file://" + (Quickshell.env("XDG_CONFIG_HOME") || (Quickshell.env("HOME") + "/.config"))
      + "/omarchy/omashortcuts/ui.ini"
    property bool showValues: true
    property string sortKey: "name"
    property bool sortDescending: false
  }
  Timer { id: validationTimer; interval: 350; onTriggered: root.validate() }
  Connections {
    target: popup
    function onBackingWindowVisibleChanged() {
      if (!popup.backingWindowVisible) root.startPicker()
    }
  }
  Process {
    id: helper
    command: ["python3", decodeURIComponent(Qt.resolvedUrl("bin/shortcuts.py").toString().replace(/^file:\/\//, ""))]
    stdinEnabled: true
    stdout: StdioCollector { id: output; waitForEnd: true }
    stderr: StdioCollector { id: errors; waitForEnd: true }
    onStarted: {
      helper.write(JSON.stringify(root.currentRequest))
      helper.stdinEnabled = false
    }
    onExited: function(code) {
      helper.stdinEnabled = true
      Qt.callLater(function() { root.finish(code, output.text, errors.text) })
    }
  }

  ShellIpc {
    target: "kel.omashortcuts"
    function open() { root.open() }
    function close() { root.close() }
    function toggle() { root.toggle() }
    function refresh() { root.refresh() }
    function status(): string {
      return JSON.stringify({
        opened: root.opened, busy: helper.running, error: root.status,
        shortcuts: root.shortcuts.length, activeCount: root.activeCount,
        editing: root.editing, valid: root.valid, actionType: root.actionType,
        textLength: textField.text.length, recording: root.recording,
        heldModifiers: root.heldModifiers, shortcut: keyField.text,
        tableRows: shortcutTable.rowCount, tableWidth: shortcutTable.width,
        selected: !!shortcutTable.selectedRow, showExisting: root.showExisting,
        valuesVisible: shortcutTable.valueColumnVisible, valueColumnWidth: shortcutTable.valueWidth,
        valuesToggleFocused: visibilityToggle.activeFocus, paused: root.paused,
        canUndoDelete: root.canUndoDelete,
        disabledCount: root.shortcuts.filter(function(row) { return row.enabled === false }).length,
        sortKey: preferences.sortKey, sortDescending: preferences.sortDescending,
        transferMode: root.transferMode, focusedSortKey: shortcutTable.focusedSortKey,
        pickerOpen: !!root.pendingPicker || (helper.running && root.filePickerRequest),
        enabledSwitchFocused: shortcutTable.enabledSwitchFocused,
        focusedControl: newButton.activeFocus ? "new" : pauseButton.activeFocus ? "pause"
          : importButton.activeFocus ? "import" : exportButton.activeFocus ? "export"
          : transferConfirm.activeFocus ? "confirmTransfer" : transferCancel.activeFocus ? "cancelTransfer"
          : browseButton.activeFocus ? "browse"
          : transferFile.activeFocus ? "transferPath" : filter.activeFocus ? "filter"
          : cancelEditButton.activeFocus ? "cancelEditor" : "",
        contentHeight: content.implicitHeight, panelHeight: popup.contentHeight
      })
    }
  }

  implicitWidth: button.implicitWidth
  implicitHeight: barSize
  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "⌨"
    tooltipText: strings.t("tooltip")
    onPressed: root.toggle()
  }
  KeyboardPanel {
    id: popup
    anchorItem: button
    bar: root.bar
    owner: root
    open: root.popupOpen
    focusTarget: content
    contentWidth: popup.fittedContentWidth(Style.space(900), 1040)
    contentHeight: popup.fittedContentHeight(content.implicitHeight, 760)

    Column {
      id: content
      width: parent.width
      spacing: Style.space(10)
      focus: true
      Keys.onEscapePressed: {
        root.recording = false
        if (root.transferMode) root.transferMode = ""
        else if (root.editing) root.editing = false
        else root.close()
      }
      RowLayout {
        width: parent.width
        PlainText {
          Layout.fillWidth: true
          text: strings.t("title")
          font.pixelSize: Style.font.subtitle
          font.bold: true
        }
        Button {
          id: newButton
          text: strings.t("new")
          enabled: !helper.running && !root.editing && root.transferMode === ""
          focusable: true
          onClicked: root.edit(null)
        }
        Button {
          text: strings.t("refresh")
          enabled: !helper.running
          focusable: true
          onClicked: root.refresh()
        }
        RowLayout {
          visible: !root.editing
          enabled: !helper.running && !root.editing && root.transferMode === ""
          PanelSeparator {
            Layout.preferredWidth: Style.space(1)
            Layout.preferredHeight: Style.space(22)
            Layout.leftMargin: Style.space(6)
            Layout.rightMargin: Style.space(6)
            foreground: Color.popups.text
          }
          Button {
            id: importButton
            text: strings.t("import")
            focusable: true
            onClicked: root.chooseFile(true)
          }
          Button {
            id: exportButton
            text: strings.t("export")
            focusable: true
            onClicked: root.chooseFile(false)
          }
          PanelSeparator {
            Layout.preferredWidth: Style.space(1)
            Layout.preferredHeight: Style.space(22)
            Layout.leftMargin: Style.space(6)
            Layout.rightMargin: Style.space(6)
            foreground: Color.popups.text
          }
          Button {
            id: pauseButton
            text: root.paused ? strings.t("resume") : strings.t("pause")
            selected: root.paused
            focusable: true
            onClicked: root.run({ operation: "pause", paused: !root.paused, revision: root.revision })
          }
        }
      }
      PlainText {
        width: parent.width
        text: strings.tn("activeCount", root.activeCount).arg(Commons.I18n.formatNumber(root.activeCount))
        opacity: 0.7
      }
      PlainText {
        width: parent.width
        visible: root.paused
        text: strings.t("pausedNotice")
        color: Border.color(popup.borderSpec)
        font.bold: true
      }
      PlainText {
        width: parent.width
        visible: root.noticeKey !== ""
        text: !root.noticeKey ? "" : root.noticeKey === "undoDisabled"
          ? strings.t(root.noticeKey).arg(root.noticeDetail) : strings.t(root.noticeKey)
        color: Border.color(popup.borderSpec)
      }
      PlainText {
        width: parent.width
        visible: root.status !== ""
        text: root.status
        font.bold: true
      }
      Column {
        width: parent.width
        spacing: Style.space(8)
        visible: root.transferMode !== ""
        PlainText {
          width: parent.width
          text: root.transferMode === "chooseImport" ? strings.t("importPathHelp")
            : root.transferMode === "chooseExport" ? strings.t("exportPathHelp")
            : root.transferMode === "export" ? strings.t("exportWarning")
            : strings.tn("importSummary", root.importAdded).arg(Commons.I18n.formatNumber(root.importAdded))
              .arg(Commons.I18n.formatNumber(root.importSkipped))
        }
        RowLayout {
          width: parent.width
          visible: root.transferMode === "chooseImport" || root.transferMode === "chooseExport"
          enabled: !helper.running
          TextField {
            id: transferFile
            Layout.fillWidth: true
            maximumLength: 4096
            placeholderText: strings.t("filePath")
            onAccepted: root.reviewTransfer()
          }
          Button {
            id: browseButton
            text: strings.t("browse")
            focusable: true
            onClicked: root.browseFile()
          }
        }
        PlainText {
          width: parent.width
          visible: root.transferMode === "import" || root.transferMode === "export"
          text: root.transferPath
          maximumLineCount: 2
          elide: Text.ElideMiddle
        }
        Row {
          spacing: Style.space(8)
          Button {
            id: transferConfirm
            text: root.transferMode === "chooseImport" ? strings.t("previewImport")
              : root.transferMode === "chooseExport" ? strings.t("reviewExport")
              : root.transferMode === "import" ? strings.t("confirmImport") : strings.t("confirmExport")
            enabled: !helper.running && (root.transferMode !== "import" || root.importAdded > 0)
              && ((root.transferMode !== "chooseImport" && root.transferMode !== "chooseExport") || !!transferFile.text.trim())
            focusable: true
            onClicked: {
              if (root.transferMode === "chooseImport" || root.transferMode === "chooseExport") root.reviewTransfer()
              else root.confirmTransfer()
            }
          }
          Button {
            id: transferCancel
            text: strings.t("cancel")
            enabled: !helper.running
            focusable: true
            onClicked: root.transferMode = ""
          }
        }
      }
      Column {
        width: parent.width
        spacing: Style.space(8)
        visible: root.editing
        enabled: !helper.running || root.currentRequest.operation === "validate"
        RowLayout {
          width: parent.width
          PlainText {
            Layout.fillWidth: true
            text: root.editingId ? strings.t("editTitle") : strings.t("createTitle")
            font.bold: true
          }
          Button {
            text: root.editingEnabled ? strings.t("enabled") : strings.t("disabled")
            selected: root.editingEnabled
            focusable: true
            onClicked: { root.editingEnabled = !root.editingEnabled; root.changed() }
          }
        }
        TextField {
          id: nameField
          width: parent.width
          maximumLength: 120
          placeholderText: strings.t("name")
          onTextChanged: root.changed()
        }
        RowLayout {
          width: parent.width
          TextField {
            id: keyField
            Layout.fillWidth: true
            maximumLength: 160
            placeholderText: strings.t("keys")
            readOnly: root.recording
            onTextChanged: root.changed()
            onActiveFocusChanged: if (!activeFocus) root.recording = false
            Keys.priority: Keys.BeforeItem
            Keys.onPressed: function(event) {
              if (!root.recording) return
              event.accepted = true
              if (event.isAutoRepeat) return
              if (event.key === Qt.Key_Escape) { root.recording = false; return }
              if (ShortcutKeys.isModifier(event.key) && root.pressedModifierKeys.indexOf(event.key) < 0)
                root.pressedModifierKeys = root.pressedModifierKeys.concat([event.key])
              var modifiers = event.modifiers | ShortcutKeys.modifierMask(root.pressedModifierKeys)
              root.heldModifiers = ShortcutKeys.modifierNames(modifiers, event.key).join(" + ")
              if (ShortcutKeys.isModifier(event.key)) return
              var chord = ShortcutKeys.chord(event.key, modifiers)
              root.unsupportedKey = chord === ""
              if (!chord) return
              keyField.text = chord
              root.recording = false
              root.changed()
            }
            Keys.onReleased: function(event) {
              if (!root.recording) return
              event.accepted = true
              if (event.isAutoRepeat) return
              root.pressedModifierKeys = root.pressedModifierKeys.filter(function(key) { return key !== event.key })
              var released = ShortcutKeys.modifierMask([event.key])
              var modifiers = (event.modifiers & ~released) | ShortcutKeys.modifierMask(root.pressedModifierKeys)
              root.heldModifiers = ShortcutKeys.modifierNames(modifiers, 0).join(" + ")
            }
          }
          Button {
            text: root.recording ? strings.t("cancel") : strings.t("record")
            enabled: !helper.running
            focusable: true
            onClicked: {
              root.recording = !root.recording
              root.heldModifiers = ""
              root.pressedModifierKeys = []
              root.unsupportedKey = false
              if (root.recording) {
                root.changed()
                keyField.forceActiveFocus()
              } else root.changed()
            }
          }
        }
        PlainText {
          width: parent.width
          visible: root.recording
          text: root.unsupportedKey ? strings.t("recordUnsupported")
            : (root.heldModifiers ? strings.t("recordHeld").arg(root.heldModifiers) : strings.t("recordHelp"))
        }
        Dropdown {
          width: parent.width
          label: strings.t("action")
          value: root.actionType
          options: [
            { value: "command", label: strings.t("commandAction") },
            { value: "text", label: strings.t("textAction") }
          ]
          onChanged: function(value) { root.actionType = value; root.changed() }
        }
        TextField {
          id: commandField
          width: parent.width
          visible: root.actionType === "command"
          maximumLength: 2048
          placeholderText: strings.t("command")
          onTextChanged: root.changed()
        }
        Controls.ScrollView {
          width: parent.width
          height: Style.space(90)
          visible: root.actionType === "text"
          clip: true
          Controls.TextArea {
            id: textField
            placeholderText: strings.t("text")
            textFormat: TextEdit.PlainText
            wrapMode: TextEdit.Wrap
            selectByMouse: true
            color: Color.popups.text
            selectionColor: Style.selectionFillFor(Color.popups.text, Color.accent)
            selectedTextColor: Color.popups.text
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            onTextChanged: root.changed()
            Keys.onTabPressed: function(event) {
              if (saveButton.enabled) saveButton.forceActiveFocus()
              else cancelEditButton.forceActiveFocus()
              event.accepted = true
            }
            background: Rectangle {
              color: "transparent"
              radius: Style.cornerRadius
              border.color: Color.popups.border
            }
          }
        }
        PlainText {
          width: parent.width
          text: root.actionType === "text" ? strings.t("textHelp") : strings.t("commandHelp")
          opacity: 0.7
          font.pixelSize: Style.font.bodySmall
        }
        PlainText {
          width: parent.width
          text: helper.running && root.currentRequest.operation === "validate"
            ? strings.t("checking") : root.validationMessage
          visible: text !== ""
        }
        Row {
          spacing: Style.space(8)
          Button {
            id: saveButton
            text: strings.t("save")
            enabled: !root.recording && root.valid && !helper.running
            focusable: true
            onClicked: root.save()
          }
          Button {
            id: cancelEditButton
            text: strings.t("cancel")
            enabled: !helper.running
            focusable: true
            onClicked: { root.recording = false; root.editing = false }
          }
        }
      }
      RowLayout {
        width: parent.width
        visible: !root.editing && root.transferMode === ""
        Button {
          text: strings.t("custom")
          selected: !root.showExisting
          focusable: true
          onClicked: { root.showExisting = false; root.deletingId = "" }
        }
        Button {
          text: strings.t("existing")
          selected: root.showExisting
          focusable: true
          onClicked: { root.showExisting = true; root.deletingId = "" }
        }
        Item { Layout.fillWidth: true }
        Button {
          id: visibilityToggle
          visible: !root.showExisting
          text: preferences.showValues ? strings.t("hideValues") : strings.t("showValues")
          focusable: true
          onClicked: {
            preferences.showValues = !preferences.showValues
            preferences.setValue("showValues", preferences.showValues)
            preferences.sync()
          }
        }
      }
      TextField {
        id: filter
        width: parent.width
        visible: !root.editing && root.transferMode === ""
        placeholderText: strings.t("filter")
      }
      ShortcutTable {
        id: shortcutTable
        width: parent.width
        visible: !root.editing && root.transferMode === ""
        entries: root.visibleRows
        nativeBindings: root.showExisting
        showValues: preferences.showValues
        busy: helper.running || root.transferMode !== ""
        sortKey: preferences.sortKey
        sortDescending: preferences.sortDescending
        onSortRequested: function(key) {
          preferences.sortDescending = preferences.sortKey === key ? !preferences.sortDescending : false
          preferences.sortKey = key
          preferences.setValue("sortKey", preferences.sortKey)
          preferences.setValue("sortDescending", preferences.sortDescending)
          preferences.sync()
        }
        onEnabledRequested: function(row, enabled) {
          if (!helper.running && !root.editing && !root.transferMode)
            root.run({ operation: "enable", id: row.id, enabled: enabled, revision: root.revision })
        }
        maximumListHeight: Style.space(root.editing ? 120 : 320)
        enabled: !root.editing
        onSelectedRowChanged: root.deletingId = ""
        onEditRequested: function(row) {
          if (!helper.running && !root.editing && !root.transferMode) root.edit(row)
        }
      }
      PlainText {
        width: parent.width
        visible: !root.editing && root.transferMode === "" && root.visibleRows.length === 0
        text: !root.showExisting && root.shortcuts.length === 0 ? strings.t("empty") : strings.t("noMatches")
      }
      RowLayout {
        width: parent.width
        visible: !root.editing && root.transferMode === "" && !root.showExisting
        enabled: !helper.running && !root.editing && root.transferMode === ""
        Button {
          text: strings.t("edit")
          enabled: !!shortcutTable.selectedRow
          focusable: true
          onClicked: root.edit(shortcutTable.selectedRow)
        }
        Button {
          text: root.deletingId ? strings.t("confirmDelete") : strings.t("delete")
          enabled: !!shortcutTable.selectedRow
          focusable: true
          onClicked: {
            var row = shortcutTable.selectedRow
            if (!row) return
            if (root.deletingId !== row.id) root.deletingId = row.id
            else root.run({ operation: "delete", id: row.id, revision: root.revision })
          }
        }
        Button {
          visible: root.canUndoDelete
          text: strings.t("undoDelete")
          focusable: true
          onClicked: root.run({ operation: "undo-delete", revision: root.revision })
        }
        Button {
          visible: root.deletingId !== ""
          text: strings.t("cancel")
          focusable: true
          onClicked: root.deletingId = ""
        }
        PlainText {
          Layout.fillWidth: true
          text: strings.t("tableHint")
          opacity: 0.7
          font.pixelSize: Style.font.bodySmall
        }
      }
      PlainText {
        width: parent.width
        text: strings.t("scope")
        opacity: 0.7
        font.pixelSize: Style.font.bodySmall
      }
    }
  }
}
