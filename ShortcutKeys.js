function modifierNames(mask, key) {
  var names = []
  if ((mask & Qt.ShiftModifier) || key === Qt.Key_Shift) names.push("SHIFT")
  if ((mask & Qt.ControlModifier) || key === Qt.Key_Control) names.push("CTRL")
  if ((mask & Qt.AltModifier) || key === Qt.Key_Alt) names.push("ALT")
  if ((mask & Qt.MetaModifier) || key === Qt.Key_Meta || key === Qt.Key_Super_L || key === Qt.Key_Super_R) names.push("SUPER")
  if ((mask & Qt.GroupSwitchModifier) || key === Qt.Key_AltGr) names.push("MOD5")
  return names
}

function isModifier(key) {
  return [Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta,
    Qt.Key_Super_L, Qt.Key_Super_R, Qt.Key_AltGr].indexOf(key) >= 0
}

function modifierMask(keys) {
  var mask = 0
  for (var i = 0; i < keys.length; i++) {
    var key = keys[i]
    if (key === Qt.Key_Shift) mask |= Qt.ShiftModifier
    if (key === Qt.Key_Control) mask |= Qt.ControlModifier
    if (key === Qt.Key_Alt) mask |= Qt.AltModifier
    if (key === Qt.Key_Meta || key === Qt.Key_Super_L || key === Qt.Key_Super_R) mask |= Qt.MetaModifier
    if (key === Qt.Key_AltGr) mask |= Qt.GroupSwitchModifier
  }
  return mask
}

function keyName(key) {
  if (key >= Qt.Key_A && key <= Qt.Key_Z) return String.fromCharCode(key)
  if (key >= Qt.Key_0 && key <= Qt.Key_9) return String.fromCharCode(key)
  if (key >= Qt.Key_F1 && key <= Qt.Key_F35) return "F" + (key - Qt.Key_F1 + 1)
  var pairs = [
    [Qt.Key_Space, "space"], [Qt.Key_Tab, "Tab"], [Qt.Key_Backtab, "Tab"],
    [Qt.Key_Return, "Return"], [Qt.Key_Enter, "KP_Enter"],
    [Qt.Key_Backspace, "BackSpace"], [Qt.Key_Delete, "Delete"],
    [Qt.Key_Insert, "Insert"], [Qt.Key_Home, "Home"], [Qt.Key_End, "End"],
    [Qt.Key_PageUp, "Prior"], [Qt.Key_PageDown, "Next"],
    [Qt.Key_Left, "Left"], [Qt.Key_Right, "Right"],
    [Qt.Key_Up, "Up"], [Qt.Key_Down, "Down"],
    [Qt.Key_Print, "Print"], [Qt.Key_Pause, "Pause"],
    [Qt.Key_Minus, "minus"], [Qt.Key_Equal, "equal"],
    [Qt.Key_Plus, "plus"], [Qt.Key_Comma, "comma"],
    [Qt.Key_Period, "period"], [Qt.Key_Slash, "slash"],
    [Qt.Key_Backslash, "backslash"], [Qt.Key_Semicolon, "semicolon"],
    [Qt.Key_Apostrophe, "apostrophe"], [Qt.Key_QuoteLeft, "grave"],
    [Qt.Key_BracketLeft, "bracketleft"], [Qt.Key_BracketRight, "bracketright"]
  ]
  for (var i = 0; i < pairs.length; i++) {
    if (pairs[i][0] === key) return pairs[i][1]
  }
  return ""
}

function chord(key, modifiers) {
  var name = keyName(key)
  if (!name) return ""
  var names = modifierNames(modifiers, key)
  if (key === Qt.Key_Backtab && names.indexOf("SHIFT") < 0) names.unshift("SHIFT")
  return names.concat([name]).join(" + ")
}
