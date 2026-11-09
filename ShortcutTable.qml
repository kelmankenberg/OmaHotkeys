import QtQuick
import QtQuick.Controls as Controls
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "TableSort.js" as TableSort

Column {
  id: root
  property var entries: []
  property bool nativeBindings: false
  property bool showValues: true
  property bool busy: false
  property string sortKey: "name"
  property bool sortDescending: false
  property string focusedSortKey: ""
  property Item focusedEnabledSwitch: null
  readonly property bool enabledSwitchFocused: focusedEnabledSwitch !== null && focusedEnabledSwitch.activeFocus
  readonly property var sortedEntries: TableSort.sorted(entries, sortKey, sortDescending)
  readonly property bool valueColumnVisible: nativeBindings || showValues
  property int maximumListHeight: Style.space(320)
  readonly property var selectedRow: list.currentIndex >= 0 && list.currentIndex < sortedEntries.length
    ? sortedEntries[list.currentIndex] : null
  readonly property int enabledWidth: nativeBindings ? 0 : Style.space(54)
  readonly property int typeWidth: Style.space(64)
  readonly property real dataWidth: Math.max(0, width - enabledWidth - typeWidth
    - Style.space((valueColumnVisible ? 40 : 32) + (nativeBindings ? 0 : 8)))
  readonly property real keyWidth: dataWidth * (valueColumnVisible ? 0.34 : 0.48)
  readonly property real descriptionWidth: valueColumnVisible ? dataWidth * 0.30 : dataWidth - keyWidth
  readonly property real valueWidth: valueColumnVisible ? dataWidth - keyWidth - descriptionWidth : 0
  readonly property int rowCount: list.count
  signal editRequested(var row)
  signal enabledRequested(var row, bool enabled)
  signal sortRequested(string key)
  onEntriesChanged: list.currentIndex = -1

  Commons.Translations { id: strings; directory: Qt.resolvedUrl("i18n") }

  function requestSort(key) {
    var id = selectedRow ? selectedRow.id : ""
    sortRequested(key)
    Qt.callLater(function() {
      if (id) list.currentIndex = root.sortedEntries.findIndex(function(row) { return row.id === id })
    })
  }

  component Cell: PlainText {
    wrapMode: Text.NoWrap
    elide: Text.ElideRight
    verticalAlignment: Text.AlignVCenter
    height: Style.space(34)
  }

  component Header: Cell {
    required property string label
    required property string field
    text: label + (root.sortKey === field ? (root.sortDescending ? " ▼" : " ▲") : "")
    font.bold: true
    activeFocusOnTab: true
    onActiveFocusChanged: {
      if (activeFocus) root.focusedSortKey = field
      else if (root.focusedSortKey === field) root.focusedSortKey = ""
    }
    Keys.onReturnPressed: root.requestSort(field)
    Keys.onEnterPressed: root.requestSort(field)
    Keys.onSpacePressed: root.requestSort(field)
    Accessible.role: Accessible.Button
    Accessible.name: label
    Rectangle {
      anchors.fill: parent
      color: "transparent"
      border.color: Color.accent
      border.width: parent.activeFocus ? 1 : 0
    }
    MouseArea {
      anchors.fill: parent
      cursorShape: Qt.PointingHandCursor
      onClicked: root.requestSort(parent.field)
    }
  }

  Rectangle {
    width: parent.width
    height: Style.space(34)
    color: Style.hoverFillFor(Color.popups.text, Color.accent)
    Row {
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.margins: Style.space(8)
      spacing: Style.space(8)
      Header { visible: !root.nativeBindings; width: root.enabledWidth; label: strings.t("columnEnabled"); field: "enabled" }
      Header { width: root.typeWidth; label: strings.t("columnType"); field: "type" }
      Header { width: root.keyWidth; label: strings.t("columnKey"); field: "shortcut" }
      Header { width: root.descriptionWidth; label: strings.t("columnDescription"); field: "name" }
      Header {
        visible: root.valueColumnVisible
        width: root.valueWidth
        label: root.nativeBindings ? strings.t("columnSubmap") : strings.t("columnValue")
        field: "value"
      }
    }
  }

  ListView {
    id: list
    width: parent.width
    height: Math.min(root.maximumListHeight, contentHeight)
    model: root.sortedEntries
    currentIndex: -1
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    activeFocusOnTab: true
    keyNavigationEnabled: true
    keyNavigationWraps: false
    Controls.ScrollBar.vertical: Controls.ScrollBar {}
    Keys.onReturnPressed: if (root.selectedRow && !root.nativeBindings) root.editRequested(root.selectedRow)
    Keys.onEnterPressed: if (root.selectedRow && !root.nativeBindings) root.editRequested(root.selectedRow)

    delegate: Rectangle {
      id: entry
      required property var modelData
      required property int index
      width: list.width
      height: Style.space(36)
      color: ListView.isCurrentItem
        ? Style.selectionFillFor(Color.popups.text, Color.accent)
        : (mouse.containsMouse ? Style.hoverFillFor(Color.popups.text, Color.accent)
          : (index % 2 ? Style.normalFillFor(Color.popups.text, Color.accent) : "transparent"))

      MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        onClicked: { list.currentIndex = entry.index; list.forceActiveFocus() }
        onDoubleClicked: {
          list.currentIndex = entry.index
          if (!root.nativeBindings) root.editRequested(entry.modelData)
        }
      }
      Row {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: Style.space(8)
        spacing: Style.space(8)
        Item {
          visible: !root.nativeBindings
          width: root.enabledWidth
          height: Style.space(34)
          ToggleSwitch {
            id: enabledSwitch
            anchors.centerIn: parent
            trackHeight: Style.space(16)
            cursorPad: Style.space(3)
            checked: entry.modelData.enabled !== false
            busy: root.busy
            hasCursor: activeFocus
            activeFocusOnTab: true
            onActiveFocusChanged: if (activeFocus) root.focusedEnabledSwitch = enabledSwitch
            Accessible.role: Accessible.CheckBox
            Accessible.name: strings.t("enabled")
            Accessible.checked: checked
            Keys.onSpacePressed: if (!root.busy) root.enabledRequested(entry.modelData, !checked)
            Keys.onReturnPressed: if (!root.busy) root.enabledRequested(entry.modelData, !checked)
            onToggled: root.enabledRequested(entry.modelData, !checked)
          }
        }
        Cell {
          width: root.typeWidth
          text: root.nativeBindings ? "\uf11c" : (entry.modelData.type === "text" ? "\uf15c" : "\uf120")
          horizontalAlignment: Text.AlignHCenter
          font.pixelSize: Style.font.icon
          opacity: entry.modelData.enabled === false ? 0.45 : 1
          Accessible.name: root.nativeBindings ? strings.t("existing")
            : (entry.modelData.type === "text" ? strings.t("textAction") : strings.t("commandAction"))
        }
        Cell { width: root.keyWidth; text: entry.modelData.shortcut; opacity: entry.modelData.enabled === false ? 0.45 : 1 }
        Cell { width: root.descriptionWidth; text: entry.modelData.name; opacity: entry.modelData.enabled === false ? 0.45 : 1 }
        Cell {
          visible: root.valueColumnVisible
          width: root.valueWidth
          text: !root.valueColumnVisible ? "" : root.nativeBindings ? (entry.modelData.submap || "")
            : (entry.modelData.type === "text" ? (entry.modelData.text || "") : (entry.modelData.command || ""))
        }
      }
      Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 1
        color: Color.popups.border
        opacity: 0.3
      }
    }
  }
}
