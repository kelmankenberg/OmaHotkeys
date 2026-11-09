# OmaHotkeys

An Omarchy top-bar widget for managing command and text keyboard shortcuts, with
live conflict checking against native and custom Hyprland bindings. Includes a
searchable shortcut table, import/export, and persistent deletion undo.

![OmaHotkeys showing command and text shortcuts, individual toggles, and undo deletion](docs/images/omahotkeys.png)

*Screen capture using fictional shortcut names and values.*

Previously named OmaShortcuts. The internal plugin ID (`kel.omashortcuts`),
storage paths, and generated binding markers retain their original names for
compatibility. Existing shortcuts and visibility preferences need no migration.

The compact table shows an action-type icon, key combination, description, and
saved text or command. Select a row to use **Edit** or **Delete**; double-click
or press Enter to edit it. Arrow keys move between rows. A document icon marks
text actions, a terminal icon marks commands, and a keyboard icon marks
read-only active bindings.
Long cells are truncated in the list; open **Edit** to see their full contents.
Use **Hide values** to remove the **Value / command** column, or **Show values**
to restore it. The choice is saved in `~/.config/omarchy/omashortcuts/ui.ini`.
This hides values in the list only; editing still displays the stored value.
The read-only active-bindings table keeps its Submap column.

Click a column header to sort ascending; click it again to reverse the order.
The sort column and direction are saved alongside the visibility preference.
Sorting does not change binding order or the saved shortcut records.

The **On** switch enables or disables an individual shortcut without deleting it.
Disabled entries are dimmed and do not reserve their key combinations. The editor
also has an Enabled/Disabled button. Conflicting combinations can be saved
disabled for review, but enabling them requires passing the conflict check.
**Pause all** temporarily deactivates every OmaHotkeys shortcut; **Resume all**
restores the individually enabled entries after checking conflicts. These states
survive shell restarts. Native and other custom bindings are unaffected.

Click the keyboard icon, choose **New shortcut**, and enter a name, shortcut,
and an action: **Command** runs a local command; **Text** types saved text
(such as an email address) into the currently focused input when you release
the shortcut. Existing command shortcuts keep working unchanged. Use only
commands you trust. Examples of shortcut syntax: `SUPER + CTRL + F10`, `ALT + F11`,
and `XF86AudioMute`. Spell the `+` key as `plus`.

Use **Record** beside the shortcut field to capture a key combination. Held
Shift, Control, Alt, and Super keys appear in the recording hint; pressing the
final key fills the field and runs the existing conflict check. Escape or
Cancel leaves the previous shortcut unchanged. Manual entry remains available,
including for keys the recorder cannot name. The compositor may intercept an
already-bound global shortcut before the recorder receives it; enter that
combination manually to check its conflict.

Text is passed literally through stdin to `wtype`, never interpreted as a shell
command, and does not change your clipboard. Typing waits up to five seconds for
held modifiers to be released; it fails explicitly rather than typing modified
keys or guessing a delay. Concurrent text actions are rejected to prevent
interleaved input. Unicode, whitespace, and multiline
text are supported up to 2048 characters. Newlines and tabs simulate Enter and
Tab, so they may submit a form, move focus, or execute a line in a terminal.
The receiving application must accept simulated keyboard input; read-only
controls and applications that block it cannot be filled. Text is stored locally
in plain text, so do not use this feature for passwords or secrets.

Edits are checked after a short debounce and again immediately before saving.
Conflicts with native bindings, other user bindings, and enabled OmaHotkeys
bindings are rejected when activating a shortcut. Editing excludes only that
shortcut's own existing binding.
Modifier order, common aliases, and key-name case are normalized with
libxkbcommon. Bindings in submaps, release bindings, catch-all bindings, and
unresolvable keys are checked conservatively. Physical keycodes are resolved
against all levels of the configured XKB layouts; unknown physical keys block
the same modifiers rather than assuming they are safe. Mouse bindings do not
block keyboard shortcuts. These conservative checks can reject combinations
that would otherwise work. Application-internal shortcuts are not visible to
Hyprland and cannot be checked.

OmaHotkeys owns only its generated file, never rewrites native/custom bindings,
and uses Omarchy's `o.bind` helper. Changes reload Hyprland, check configuration
errors, verify the bindings were applied, and restore the previous files on
failure. A revision check prevents stale windows from overwriting newer edits.
Refresh to see changes made in another window or outside the plugin.

## Deleting and undoing shortcuts

In **Your shortcuts**, select a row, click **Delete** below the table, then
**Confirm delete**. Native and other custom bindings in **All active bindings**
are read-only.

**Undo deletion** appears beside the editing/deletion buttons whenever a deleted
shortcut can be restored. Only the most recent deletion can be undone, including
after restarting the shell or computer. A newer deletion replaces the previous
undo record; other edits, imports, and pause changes preserve it.

Undo restores the original shortcut, identifier, and individual enabled state.
If an enabled shortcut now conflicts with another binding, it is restored
**disabled**, with a message identifying the conflict. Global pause remains
unchanged. A successful undo consumes the record; failed restoration keeps it
available. Storage limits and required runtime tools still apply.

The deleted shortcut's full text/command is retained locally in plain text for
undo, and automatic backups may also retain it. Exports include only current
shortcuts, not the deleted undo record.

## Import, export, and backups

**Export** lets you select a destination with **Browse**, or enter a full local
JSON file path inside the widget. Choosing a location does not write the file;
the plain-text warning must still be confirmed. It includes all shortcuts, their individual
enabled states, and full text/command values, even when values are hidden in the
table. Files are created with owner-only permissions. An explicitly selected
existing destination is replaced after confirmation; managed configuration and
plugin files cannot be overwritten.

**Import** lets you **Browse** for a JSON file in any accessible folder, or enter
its full local path (including `~/` paths). Selecting a file does not import it;
preview how many shortcuts will be added or skipped, then confirm. Confirmation
appends new entries **disabled for review**, with new identifiers; existing
shortcuts are never replaced. Identical type/key/name/value entries are skipped,
regardless of their identifier or enabled state. Review imported commands before
enabling them. Conflicting imported keys can remain disabled until resolved.
Files changed after preview must be previewed again.

Imports accept OmaHotkeys exports (`format: "OmaHotkeys"`, `version: 1`,
`shortcuts: [...]`) and the existing version-1 internal JSON format. Global pause
and table preferences are not imported or exported. Imports and stored state are
limited to 1 MiB and 200 shortcuts.

Before each configuration change, the previous JSON is saved privately in
`~/.config/omarchy/omashortcuts/backups/`. The latest ten automatic backups are
retained; they contain the same plain-text values as exports. To recover entries,
import a backup and review/enable the restored disabled entries. This adds missing
or changed entries rather than replacing the current configuration.

## Installation

Requires an Omarchy installation using the Quickshell bar and Lua Hyprland
configuration, Python 3, `hyprctl`, and `libxkbcommon.so.0`. Text actions also
require `wtype` (normally preinstalled by Omarchy); missing support is reported
instead of saving a nonworking text shortcut. Typing errors produce a desktop
notification and a diagnostic in the session logs.
The import/export **Browse** buttons use `zenity` for native Open/Save dialogs.
If missing, install it with `omarchy pkg add zenity`; manual paths remain available.

1. Put this directory in `~/.config/omarchy/plugins/kel.omashortcuts` (or symlink
   it there). Keep the source directory if using a symlink.
2. Create `~/.config/omarchy/omashortcuts/shortcuts.json` containing
   `{"version": 1, "shortcuts": []}`.
3. Create `~/.config/hypr/omashortcuts.lua` containing this line and a trailing
   newline:
   ```lua
   -- Generated by OmaShortcuts. Manage these bindings in the bar widget.
   ```
4. Back up `~/.config/hypr/hyprland.lua`, then add this once at its end:
   ```lua
   dofile((os.getenv("XDG_CONFIG_HOME") or (os.getenv("HOME") .. "/.config")) .. "/hypr/omashortcuts.lua")
   ```
5. Run `hyprctl reload` and `hyprctl configerrors`. Resolve any errors first.
6. Run `omarchy-shell shell rescanPlugins`, then
   `omarchy plugin enable kel.omashortcuts --section right`.

User data lives outside the plugin directory, so saving a shortcut does not
hot-reload the entire shell. Do not hand-edit the JSON or generated Lua file.
If they disagree after an interrupted save, stop editing in the widget,
back up both files, and regenerate the Lua from the JSON:

```bash
python3 - <<'PY'
import importlib.util
import json
from pathlib import Path
import os
spec = importlib.util.spec_from_file_location(
    "shortcuts", Path.home() / ".config/omarchy/plugins/kel.omashortcuts/bin/shortcuts.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
payload = json.loads((config / "omarchy/omashortcuts/shortcuts.json").read_text())
rows = payload["shortcuts"]
store = module.Store(config)
for row in rows:
    store.check_row(row)
module.atomic_write(config / "hypr/omashortcuts.lua", module.render(rows, payload.get("paused", False)))
PY
hyprctl reload
hyprctl configerrors
```

To uninstall, disable the widget with `omarchy plugin disable kel.omashortcuts`,
remove the added `dofile` line, and reload Hyprland. This also deactivates all
OmaHotkeys bindings. Keep the data files if you want to reinstall.

## Planned for future versions

These features are planned but not yet implemented:

- Categories or tags for organizing shortcuts.
- Application-specific shortcuts.
- Duplicate an existing shortcut as a starting point.
- Text templates with date/time and reusable variables.
- Safe previews of text expansions and command details before execution.
- Richer conflict details identifying a binding's source.
- Resizable columns and saved table layouts.

## Development

English strings use the Omarchy translation API and fall back to English when
another language is selected. All names, commands, and diagnostic text render
as plain text; the plugin makes no network requests.

```bash
python3 -m unittest discover -s tests -v
qmllint BarWidget.qml PlainText.qml ShortcutTable.qml ShortcutKeys.js TableSort.js
node tests/test_shortcut_keys.js
node tests/test_table_sort.js
```
