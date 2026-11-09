const assert = require("node:assert/strict")
const fs = require("node:fs")
const vm = require("node:vm")
const path = require("node:path")
const context = vm.createContext({})
vm.runInContext(fs.readFileSync(path.join(__dirname, "../TableSort.js"), "utf8"), context)
const rows = [
  { id: "a", name: "Zulu", shortcut: "SUPER + Z", command: "echo Z", enabled: true },
  { id: "b", name: "alpha", shortcut: "ALT + A", type: "text", text: "<b>literal</b>", enabled: false },
  { id: "c", name: "ALPHA", shortcut: "SUPER + A", type: "text", text: "Z text" }
]
const ids = result => result.map(row => row.id).join(",")
assert.equal(ids(context.sorted(rows, "name", false)), "b,c,a")
assert.equal(ids(context.sorted(rows, "name", true)), "a,b,c")
assert.equal(ids(context.sorted(rows, "shortcut", false)), "b,c,a")
assert.equal(ids(context.sorted(rows, "enabled", false)), "b,a,c")
assert.equal(ids(context.sorted(rows, "type", false)), "a,b,c")
assert.equal(ids(context.sorted(rows, "value", false)), "b,a,c")
assert.equal(ids(context.sorted(rows, "unknown", false)), "b,c,a")
assert.equal(ids(rows), "a,b,c")
assert.equal(context.value({ submap: "resize" }, "value"), "resize")
assert.equal(context.value(rows[1], "value"), "<b>literal</b>")
assert.equal(context.sorted([], "name", false).length, 0)
console.log("Table sorting, stable ties, and literal values passed.")
