function value(row, key) {
  if (key === "type") return row.type || "command"
  if (key === "value") return row.submap || (row.type === "text" ? row.text : row.command) || ""
  if (key === "enabled") return row.enabled === false ? "0" : "1"
  return String(row[key] || "")
}

function sorted(rows, key, descending) {
  if (["enabled", "type", "shortcut", "name", "value"].indexOf(key) < 0) key = "name"
  return rows.map(function(row, index) { return { row: row, index: index } }).sort(function(a, b) {
    var left = value(a.row, key).toLowerCase()
    var right = value(b.row, key).toLowerCase()
    var comparison = left.localeCompare(right)
    if (comparison === 0) return a.index - b.index
    return descending ? -comparison : comparison
  }).map(function(item) { return item.row })
}
