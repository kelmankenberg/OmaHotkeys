const assert = require("node:assert/strict")
const fs = require("node:fs")
const vm = require("node:vm")
const path = require("node:path")

const source = fs.readFileSync(path.join(__dirname, "../ShortcutKeys.js"), "utf8")
const Qt = {}
let next = 1000
for (const name of new Set(source.match(/Qt\.\w+/g))) Qt[name.slice(3)] = next++
Object.assign(Qt, {
  ShiftModifier: 1, ControlModifier: 2, AltModifier: 4, MetaModifier: 8,
  GroupSwitchModifier: 16, Key_A: 65, Key_Z: 90, Key_0: 48, Key_9: 57,
  Key_F1: 2000, Key_F35: 2034
})
const context = vm.createContext({ Qt })
vm.runInContext(source, context)
assert.equal(context.modifierNames(0, Qt.Key_Shift).join(" + "), "SHIFT")
assert.equal(context.modifierNames(0, Qt.Key_Control).join(" + "), "CTRL")
assert.equal(context.modifierNames(0, Qt.Key_Alt).join(" + "), "ALT")
assert.equal(context.modifierNames(0, Qt.Key_Meta).join(" + "), "SUPER")
assert.equal(context.modifierNames(0, Qt.Key_Super_R).join(" + "), "SUPER")
assert.equal(context.modifierNames(15, 0).join(" + "), "SHIFT + CTRL + ALT + SUPER")
assert.equal(context.chord(Qt.Key_A, 14), "CTRL + ALT + SUPER + A")
assert.equal(context.chord(Qt.Key_F1 + 9, 9), "SHIFT + SUPER + F10")
assert.equal(context.chord(Qt.Key_Space, 8), "SUPER + space")
assert.equal(context.chord(Qt.Key_Plus, 1), "SHIFT + plus")
assert.equal(context.chord(Qt.Key_Backtab, 0), "SHIFT + Tab")
assert.equal(context.chord(Qt.Key_Control, 2), "")
assert.equal(context.chord(-1, 0), "")
assert.equal(context.isModifier(Qt.Key_Shift), true)
assert.equal(context.isModifier(Qt.Key_A), false)
assert.equal(context.modifierNames(8, 0).join(" + "), "SUPER")
assert.equal(context.modifierMask([Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta]), 15)
assert.equal(context.modifierMask([Qt.Key_Control, Qt.Key_Super_R]), 10)
assert.equal(context.modifierMask([]), 0)
console.log("Shortcut recorder modifier and chord checks passed.")
