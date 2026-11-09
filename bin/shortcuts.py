#!/usr/bin/env python3
"""Own only OmaHotkeys bindings; validate against the live compositor."""

import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from urllib.parse import unquote, urlsplit


_UNCHANGED = object()


class ShortcutError(Exception):
    pass


MODIFIERS = {
    "SHIFT": 1, "CAPS": 2, "CTRL": 4, "ALT": 8, "MOD2": 16,
    "MOD3": 32, "SUPER": 64, "MOD5": 128,
}
ALIASES = {
    "CONTROL": "CTRL", "CTL": "CTRL", "WIN": "SUPER",
    "META": "SUPER", "MOD4": "SUPER", "MOD1": "ALT",
}
KEY_ALIASES = {
    "esc": "Escape", "enter": "Return", "spacebar": "space",
    "plus": "plus", "minus": "minus", "pageup": "Prior",
    "pagedown": "Next", "pgup": "Prior", "pgdn": "Next",
}
MODIFIER_QUERY = "return " + " or ".join(
    f'hl.is_key_down("{key}")' for key in (
        "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
        "Super_L", "Super_R", "Meta_L", "Meta_R", "ISO_Level3_Shift", "ISO_Level5_Shift",
    )
)


class Keysyms:
    def __init__(self):
        self.lib = ctypes.CDLL("libxkbcommon.so.0")
        self.lib.xkb_keysym_from_name.argtypes = [ctypes.c_char_p, ctypes.c_int]
        self.lib.xkb_keysym_from_name.restype = ctypes.c_uint32
        self.lib.xkb_keysym_get_name.argtypes = [
            ctypes.c_uint32, ctypes.c_char_p, ctypes.c_size_t,
        ]
        self.lib.xkb_keysym_get_name.restype = ctypes.c_int
        self.lib.xkb_keysym_to_lower.argtypes = [ctypes.c_uint32]
        self.lib.xkb_keysym_to_lower.restype = ctypes.c_uint32

    def resolve(self, key):
        key = KEY_ALIASES.get(key.lower(), key)
        symbol = self.lib.xkb_keysym_from_name(key.encode(), 1)
        if not symbol:
            raise ShortcutError("Unknown key. Use an XKB key name, such as F10, space, or XF86AudioMute.")
        symbol = self.lib.xkb_keysym_to_lower(symbol)
        name = ctypes.create_string_buffer(128)
        if self.lib.xkb_keysym_get_name(symbol, name, len(name)) <= 0:
            raise ShortcutError("Cannot resolve this key.")
        return symbol, name.value.decode()

    def parse(self, text):
        if not isinstance(text, str) or len(text) > 160:
            raise ShortcutError("Enter a shortcut of at most 160 characters.")
        parts = [part.strip() for part in text.split("+")]
        if not parts or any(not part for part in parts):
            raise ShortcutError("Use modifiers + one key; spell the + key as 'plus'.")
        mask = 0
        for part in parts[:-1]:
            modifier = ALIASES.get(part.upper(), part.upper())
            if modifier not in MODIFIERS:
                raise ShortcutError(f"Unknown modifier: {part}")
            bit = MODIFIERS[modifier]
            if mask & bit:
                raise ShortcutError(f"Repeated modifier: {modifier}")
            mask |= bit
        symbol, name = self.resolve(parts[-1])
        canonical = " + ".join(
            [mod for mod, bit in MODIFIERS.items() if mask & bit] + [name]
        )
        return mask, symbol, canonical

    def physical_symbols(self, names, codes, source=None):
        class Names(ctypes.Structure):
            _fields_ = [(field, ctypes.c_char_p) for field in
                        ("rules", "model", "layout", "variant", "options")]

        lib = self.lib
        lib.xkb_context_new.argtypes = [ctypes.c_int]
        lib.xkb_context_new.restype = ctypes.c_void_p
        lib.xkb_context_unref.argtypes = [ctypes.c_void_p]
        lib.xkb_keymap_new_from_names.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(Names), ctypes.c_int,
        ]
        lib.xkb_keymap_new_from_names.restype = ctypes.c_void_p
        lib.xkb_keymap_new_from_string.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int,
        ]
        lib.xkb_keymap_new_from_string.restype = ctypes.c_void_p
        lib.xkb_keymap_unref.argtypes = [ctypes.c_void_p]
        lib.xkb_keymap_num_layouts_for_key.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        lib.xkb_keymap_num_layouts_for_key.restype = ctypes.c_uint32
        lib.xkb_keymap_num_levels_for_key.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
        ]
        lib.xkb_keymap_num_levels_for_key.restype = ctypes.c_uint32
        lib.xkb_keymap_key_get_syms_by_level.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_uint32)),
        ]
        lib.xkb_keymap_key_get_syms_by_level.restype = ctypes.c_int
        context = lib.xkb_context_new(0)
        if not context:
            raise ShortcutError("Cannot create an XKB context.")
        keymap = None
        try:
            if source is not None:
                keymap = lib.xkb_keymap_new_from_string(context, source, 1, 0)
            else:
                values = Names(*(names[field].encode() for field, _ in Names._fields_))
                keymap = lib.xkb_keymap_new_from_names(context, ctypes.byref(values), 0)
            if not keymap:
                raise ShortcutError("Cannot compile the configured keyboard layout; physical-key conflicts cannot be checked.")
            result = {}
            for code in codes:
                symbols = set()
                for layout in range(lib.xkb_keymap_num_layouts_for_key(keymap, code)):
                    for level in range(lib.xkb_keymap_num_levels_for_key(keymap, code, layout)):
                        pointer = ctypes.POINTER(ctypes.c_uint32)()
                        count = lib.xkb_keymap_key_get_syms_by_level(
                            keymap, code, layout, level, ctypes.byref(pointer),
                        )
                        symbols.update(lib.xkb_keysym_to_lower(pointer[i]) for i in range(count))
                result[code] = symbols
            return result
        finally:
            if keymap:
                lib.xkb_keymap_unref(keymap)
            lib.xkb_context_unref(context)


def lua_string(value):
    # JSON's Unicode escapes are not Lua escapes. Preserve UTF-8 literally.
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def description(row):
    return f"OmaShortcuts [{row['id']}]: {row['name']}"


def action_command(row):
    if row.get("type", "command") == "text":
        return (
            'python3 "${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/'
            'kel.omashortcuts/bin/shortcuts.py" type ' + shlex.quote(row["id"])
        )
    return row["command"]


def render(rows, paused=False):
    lines = ["-- Generated by OmaShortcuts. Manage these bindings in the bar widget."]
    for row in rows:
        if paused or not row.get("enabled", True):
            continue
        options = ", { release = true }" if row.get("type") == "text" else ""
        lines.append(
            f"o.bind({lua_string(row['shortcut'])}, "
            f"{lua_string(description(row))}, {lua_string(action_command(row))}{options})"
        )
    return ("\n".join(lines) + "\n").encode()


def export_data(rows):
    return (json.dumps({
        "format": "OmaHotkeys", "version": 1, "shortcuts": rows,
    }, ensure_ascii=False, indent=2) + "\n").encode()


def atomic_write(path, data, overwrite=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Store:
    def __init__(self, config=None, runner=subprocess.run):
        self.config = Path(config or os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        self.directory = self.config / "omarchy/omashortcuts"
        self.data = self.directory / "shortcuts.json"
        self.lua = self.config / "hypr/omashortcuts.lua"
        self.main = self.config / "hypr/hyprland.lua"
        self.runner = runner
        self.keys = Keysyms()
        self.paused = False
        self.deleted_row = None

    def hypr(self, *args, as_json=False):
        result = self.runner(
            ["hyprctl", *(["-j"] if as_json else []), *args],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if result.returncode:
            raise ShortcutError(f"Hyprland request failed: {result.stderr.strip() or result.stdout.strip()}")
        if as_json:
            return json.loads(result.stdout)
        if args == ("binds",):
            return result.stdout
        return result.stdout.strip()

    def reload(self):
        reply = self.hypr("reload")
        if reply != "ok":
            raise ShortcutError(f"Hyprland reload failed: {reply}")
        errors = self.hypr("configerrors")
        if errors:
            raise ShortcutError(f"Hyprland configuration errors: {errors}")

    def binds(self):
        # Omarchy's Lua Hyprland provider loses code: keys in JSON output.
        text = self.hypr("binds")
        if len(text) > 4 * 1024 * 1024:
            raise ShortcutError("Hyprland's binding list is too large.")
        records = []
        current = None
        for line in text.splitlines():
            if re.fullmatch(r"bind[a-z]*", line):
                flags = line[4:]
                current = {"mouse": "m" in flags, "ignore_mods": "i" in flags, "release": "r" in flags}
                records.append(current)
            elif line.strip():
                match = re.fullmatch(r"\t([a-z_]+): (.*)", line)
                if current is None or not match or match[1] in current:
                    raise ShortcutError("Cannot safely parse Hyprland's binding list.")
                current[match[1]] = match[2]
        codes = set()
        for bind in records:
            if not {"modmask", "key", "keycode", "dispatcher", "arg"}.issubset(bind):
                raise ShortcutError("Hyprland returned an incomplete binding record.")
            bind["modmask"] = int(bind["modmask"])
            bind["keycode"] = int(bind["keycode"])
            if not 0 <= bind["modmask"] <= 255 or not 0 <= bind["keycode"] <= 0xFFFFFFFF:
                raise ShortcutError("Hyprland returned an invalid modifier mask or keycode.")
            bind["catch_all"] = bind.get("catchall", "false") == "true"
            bind["key"] = bind["key"].split(" + ")[-1]
            if bind["key"].startswith("code:"):
                bind["keycode"] = int(bind["key"][5:])
                bind["key"] = ""
            bind["mouse"] = bind["mouse"] or bind["key"].startswith("mouse")
            if bind["keycode"]:
                if not 0 < bind["keycode"] <= 0xFFFFFFFF:
                    raise ShortcutError("Hyprland returned an invalid physical keycode.")
                codes.add(bind["keycode"])
        if codes:
            names = {}
            for field in ("rules", "model", "layout", "variant", "options"):
                option = self.hypr("getoption", f"input:kb_{field}", as_json=True)
                if not isinstance(option.get("str"), str):
                    raise ShortcutError("Cannot read the configured XKB layout.")
                names[field] = "" if option["str"] == "[[EMPTY]]" else option["str"]
            file_option = self.hypr("getoption", "input:kb_file", as_json=True)
            keymap_file = file_option.get("str")
            if not isinstance(keymap_file, str):
                raise ShortcutError("Cannot read the configured XKB keymap file option.")
            source = None
            if keymap_file not in ("", "[[EMPTY]]"):
                path = Path(os.path.expandvars(keymap_file)).expanduser()
                with path.open("rb") as stream:
                    source = stream.read(2 * 1024 * 1024 + 1)
                if len(source) > 2 * 1024 * 1024:
                    raise ShortcutError("The configured XKB keymap file is too large.")
            symbols = self.keys.physical_symbols(names, codes, source)
            for bind in records:
                if bind["keycode"]:
                    bind["symbols"] = symbols[bind["keycode"]]
        return records

    def load(self):
        if not self.data.is_file() or not self.lua.is_file():
            raise ShortcutError("OmaHotkeys is not installed. Follow README.md before enabling it.")
        raw = self.data.read_bytes()
        if len(raw) > 1024 * 1024:
            raise ShortcutError("Shortcut data is too large.")
        payload = json.loads(raw)
        if (not isinstance(payload, dict) or type(payload.get("version")) is not int
                or payload["version"] != 1):
            raise ShortcutError("Unsupported shortcut data format.")
        self.paused = payload.get("paused", False)
        if not isinstance(self.paused, bool):
            raise ShortcutError("Invalid pause state.")
        rows = payload.get("shortcuts")
        if not isinstance(rows, list) or len(rows) > 200:
            raise ShortcutError("Invalid shortcut list (maximum 200).")
        seen = set()
        for row in rows:
            self.check_row(row)
            if row["id"] in seen:
                raise ShortcutError("Duplicate shortcut identifier.")
            seen.add(row["id"])
        self.deleted_row = payload.get("deleted")
        if self.deleted_row is not None:
            self.check_row(self.deleted_row, check_runtime=False)
        if self.lua.read_bytes() != render(rows, self.paused):
            raise ShortcutError("The managed Lua file was changed outside OmaHotkeys. Restore it before editing.")
        return rows, hashlib.sha256(raw).hexdigest()

    def check_row(self, row, *, check_runtime=True):
        if not isinstance(row, dict):
            raise ShortcutError("Invalid shortcut record.")
        try:
            if str(uuid.UUID(row["id"])) != row["id"]:
                raise ValueError()
        except (KeyError, ValueError, TypeError, AttributeError) as error:
            raise ShortcutError("Invalid shortcut identifier.") from error
        kind = row.get("type", "command")
        if kind not in ("command", "text"):
            raise ShortcutError("Action must be Command or Text.")
        if not isinstance(row.get("enabled", True), bool):
            raise ShortcutError("Enabled state must be true or false.")
        fields = (("name", 120), ("command", 2048)) if kind == "command" else (("name", 120),)
        for key, maximum in fields:
            value = row.get(key)
            if not isinstance(value, str) or not value.strip() or len(value) > maximum:
                raise ShortcutError(f"{key.capitalize()} is required (maximum {maximum} characters).")
            if any(ord(char) < 32 or ord(char) == 127 for char in value):
                raise ShortcutError(f"{key.capitalize()} must be a single line without control characters.")
        if kind == "text":
            value = row.get("text")
            if not isinstance(value, str) or not value or len(value) > 2048:
                raise ShortcutError("Text is required (maximum 2048 characters).")
            if any((ord(char) < 32 and char not in "\n\t") or ord(char) == 127 for char in value):
                raise ShortcutError("Text cannot contain control characters other than newlines and tabs.")
            if check_runtime and row.get("enabled", True) and not shutil.which("wtype"):
                raise ShortcutError("Text shortcuts require wtype. Install it with: omarchy pkg add wtype")
        return self.keys.parse(row.get("shortcut"))

    def conflicts(self, candidate, rows, binds):
        mask, symbol, _ = self.check_row(candidate)
        old = next((row for row in rows if row["id"] == candidate["id"]), None)
        conflicts = []
        # Never exclude all plugin bindings: only the exact row being edited.
        skipped_old = False
        for bind in binds:
            if int(bind["modmask"]) != mask and not bind.get("ignore_mods"):
                continue
            if bind.get("mouse"):
                continue
            if old and old.get("enabled", True) and not skipped_old and bind.get("description") == description(old):
                old_mask, old_symbol, _ = self.keys.parse(old["shortcut"])
                if not bind.get("keycode") and not bind.get("catch_all"):
                    _, bind_symbol, _ = self.keys.parse(bind["key"])
                    if old_mask == mask and old_symbol == bind_symbol:
                        skipped_old = True
                        continue
            code = bind.get("keycode", 0)
            matches = bool(bind.get("catch_all"))
            if code:
                matches = matches or not bind.get("symbols") or symbol in bind["symbols"]
            elif not matches:
                # Unresolvable live bindings cannot be assumed safe.
                try:
                    live_symbol, _ = self.keys.resolve(bind["key"])
                except ShortcutError:
                    matches = True
                else:
                    matches = live_symbol == symbol
            if matches:
                label = bind.get("description") or bind.get("dispatcher") or "Existing binding"
                if code:
                    label += f" (physical keycode {code})"
                if bind.get("submap"):
                    label += f" (submap: {bind['submap']})"
                conflicts.append(label[:300])
        for row in rows:
            if row["id"] != candidate["id"] and row.get("enabled", True):
                other_mask, other_symbol, _ = self.keys.parse(row["shortcut"])
                if (other_mask, other_symbol) == (mask, symbol):
                    label = description(row)
                    if label not in conflicts:
                        conflicts.append(label)
        return conflicts

    def verify(self, rows, binds, paused=False):
        for row in rows:
            if paused or not row.get("enabled", True):
                if any(bind.get("description") == description(row) for bind in binds):
                    raise ShortcutError("A disabled or paused shortcut is still active.")
                continue
            mask, symbol, _ = self.keys.parse(row["shortcut"])
            matches = [
                bind for bind in binds
                if bind.get("description") == description(row)
                and bind["modmask"] == mask and not bind.get("keycode")
                and bind.get("release", False) == (row.get("type") == "text")
                and self.keys.resolve(bind["key"])[0] == symbol
            ]
            if len(matches) != 1:
                raise ShortcutError("Managed bindings are not loaded exactly once. Check the Hyprland loader.")
            collision = self.conflicts(row, rows, binds)
            if collision:
                raise ShortcutError("Conflict: " + "; ".join(collision))

    def backup(self, raw):
        directory = self.directory / "backups"
        directory.mkdir(mode=0o700, exist_ok=True)
        path = directory / f"backup-{time.time_ns()}-{uuid.uuid4().hex}.json"
        atomic_write(path, raw)
        owned = sorted(
            item for item in directory.iterdir()
            if re.fullmatch(r"backup-\d+-[a-f0-9]{32}\.json", item.name) and item.is_file()
        )
        for item in owned[:-10]:
            item.unlink()
        return str(path)

    def commit(self, rows, old_rows, paused=None, deleted_row=_UNCHANGED):
        paused = self.paused if paused is None else paused
        deleted_row = self.deleted_row if deleted_row is _UNCHANGED else deleted_row
        payload = {"version": 1, "paused": paused, "shortcuts": rows}
        if deleted_row is not None:
            self.check_row(deleted_row, check_runtime=False)
            payload["deleted"] = deleted_row
        data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
        if max(len(data), len(export_data(rows))) > 1024 * 1024:
            raise ShortcutError("Shortcut data would exceed the 1 MiB limit.")
        previous_data = self.data.read_bytes()
        previous_lua = self.lua.read_bytes()
        try:
            backup = self.backup(previous_data)
            atomic_write(self.lua, render(rows, paused))
            self.reload()
            binds = self.binds()
            self.verify(rows, binds, paused)
            deleted = {description(row) for row in old_rows} - {description(row) for row in rows}
            if any(bind.get("description") in deleted for bind in binds):
                raise ShortcutError("A removed shortcut is still active.")
            atomic_write(self.data, data)
        except (ShortcutError, OSError, ValueError, subprocess.SubprocessError) as error:
            try:
                atomic_write(self.lua, previous_lua)
                atomic_write(self.data, previous_data)
                self.reload()
            except (ShortcutError, OSError, subprocess.SubprocessError) as rollback:
                raise ShortcutError(f"Save failed: {error}. Rollback also failed: {rollback}") from error
            raise ShortcutError(f"Save failed; previous shortcuts restored: {error}") from error
        self.paused = paused
        self.deleted_row = deleted_row
        return backup

    def file_path(self, value):
        if not isinstance(value, str) or not value or len(value) > 4096 or "\0" in value:
            raise ShortcutError("Choose a local JSON file.")
        if value.startswith("file:"):
            url = urlsplit(value)
            if url.scheme != "file" or url.netloc not in ("", "localhost") or url.query or url.fragment:
                raise ShortcutError("Only local files are supported.")
            path = Path(unquote(url.path))
        else:
            path = Path(value).expanduser()
        if not path.is_absolute():
            raise ShortcutError("Choose an absolute local file path.")
        return path.resolve()

    def import_rows(self, value, rows):
        path = self.file_path(value)
        if not path.is_file():
            raise ShortcutError("Choose an existing JSON file.")
        with path.open("rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ShortcutError("Import file is too large (maximum 1 MiB).")
        payload = json.loads(raw)
        if (not isinstance(payload, dict) or type(payload.get("version")) is not int or payload["version"] != 1
                or payload.get("format", "OmaHotkeys") != "OmaHotkeys"):
            raise ShortcutError("Unsupported import format.")
        incoming = payload.get("shortcuts")
        if not isinstance(incoming, list) or len(incoming) > 200:
            raise ShortcutError("Invalid import list (maximum 200 shortcuts).")

        def identity(row):
            kind = row.get("type", "command")
            return (kind, self.keys.parse(row["shortcut"])[2], row["name"],
                    row["text"] if kind == "text" else row["command"])

        seen = {identity(row) for row in rows}
        added = []
        skipped = 0
        for item in incoming:
            if not isinstance(item, dict):
                raise ShortcutError("Invalid imported shortcut.")
            row = {
                "id": item.get("id", str(uuid.uuid4())), "type": item.get("type", "command"),
                "name": item.get("name"), "shortcut": item.get("shortcut"), "enabled": False,
            }
            if "enabled" in item and not isinstance(item["enabled"], bool):
                raise ShortcutError("Invalid imported enabled state.")
            field = "text" if row["type"] == "text" else "command"
            row[field] = item.get(field)
            _, _, row["shortcut"] = self.check_row(row)
            key = identity(row)
            if key in seen:
                skipped += 1
                continue
            seen.add(key)
            row["id"] = str(uuid.uuid4())
            added.append(row)
        if len(rows) + len(added) > 200:
            raise ShortcutError("Import would exceed the 200-shortcut limit.")
        return added, skipped, hashlib.sha256(raw).hexdigest()

    def choose_file(self, request):
        if not shutil.which("zenity"):
            raise ShortcutError("File browsing requires zenity. Install it with: omarchy pkg add zenity")
        saving = request["operation"] == "choose-export"
        path = self.file_path(request.get("path"))
        title = request.get("title", "Export OmaHotkeys shortcuts" if saving else "Import OmaHotkeys shortcuts")
        label = request.get("filterLabel", "JSON files")
        for value in (title, label):
            if (not isinstance(value, str) or not value.strip() or len(value) > 200
                    or any(ord(char) < 32 or ord(char) == 127 for char in value)):
                raise ShortcutError("Invalid file chooser label.")
        result = self.runner(
            ["zenity", "--file-selection", *(["--save"] if saving else []), "--title=" + title,
             "--filename=" + str(path), "--file-filter=" + label + " | *.json"],
            capture_output=True, text=True, timeout=600, check=False,
        )
        if result.returncode == 1:
            return {"ok": True, "cancelled": True}
        if result.returncode:
            raise ShortcutError(
                f"File chooser failed: {result.stderr.strip() or 'exit status ' + str(result.returncode)}"
            )
        selected = self.file_path(result.stdout.removesuffix("\n"))
        if not saving and not selected.is_file():
            raise ShortcutError("Choose an existing JSON file.")
        return {"ok": True, "path": str(selected)}

    def export_rows(self, request, rows):
        if request.get("confirmed") is not True:
            raise ShortcutError("Confirm that exports contain stored text and commands in plain text.")
        path = self.file_path(request.get("path"))
        protected = (self.directory.resolve(), (self.config / "omarchy/plugins/kel.omashortcuts").resolve())
        if path in (self.lua.resolve(), self.main.resolve()) or any(path.is_relative_to(item) for item in protected):
            raise ShortcutError("Exports cannot overwrite OmaHotkeys configuration or plugin files.")
        data = export_data(rows)
        if path.exists() and request.get("overwrite") is not True:
            raise ShortcutError("The export file already exists. Choose another filename.")
        atomic_write(path, data, overwrite=request.get("overwrite") is True)
        return str(path)

    def handle(self, request):
        if not isinstance(request, dict):
            raise ShortcutError("Invalid request.")
        operation = request.get("operation")
        if operation in ("choose-export", "choose-import"):
            return self.choose_file(request)
        if operation not in ("list", "validate", "save", "delete", "undo-delete", "enable", "pause", "preview-import", "import", "export"):
            raise ShortcutError("Unknown operation.")
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / "lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            rows, revision = self.load()
            details = {}
            if operation in ("save", "delete", "undo-delete", "enable", "pause", "import", "export"):
                if request.get("revision") != revision:
                    raise ShortcutError("Shortcuts changed in another window. Refresh before saving.")
            if operation in ("save", "delete", "undo-delete", "enable", "pause", "import"):
                self.reload()
            errors = self.hypr("configerrors")
            if errors:
                raise ShortcutError(f"Fix existing Hyprland configuration errors first: {errors}")
            binds = self.binds()
            if operation in ("validate", "save"):
                row = {
                    "id": request.get("id") or str(uuid.uuid4()),
                    "name": request.get("name", ""),
                    "shortcut": request.get("shortcut", ""),
                    "type": request.get("type", "command"),
                    "enabled": request.get("enabled", True),
                }
                if row["type"] == "text":
                    row["text"] = request.get("text", "")
                else:
                    row["command"] = request.get("command", "")
                if request.get("id") and not any(item["id"] == row["id"] for item in rows):
                    raise ShortcutError("This shortcut no longer exists. Refresh the list.")
                _, _, row["shortcut"] = self.check_row(row)
                row["name"] = row["name"].strip()
                if row["type"] == "command":
                    row["command"] = row["command"].strip()
                conflicts = self.conflicts(row, rows, binds)
                if operation == "validate":
                    return {
                        "ok": True, "valid": not conflicts or not row["enabled"], "conflicts": conflicts,
                        "canonical": row["shortcut"],
                    }
                if conflicts and row["enabled"]:
                    raise ShortcutError("Conflict: " + "; ".join(conflicts))
                updated = [row if item["id"] == row["id"] else item for item in rows]
                if not request.get("id"):
                    if len(rows) >= 200:
                        raise ShortcutError("Maximum 200 shortcuts reached.")
                    updated.append(row)
                self.commit(updated, rows)
            elif operation == "delete":
                deleted_row = next((row for row in rows if row["id"] == request.get("id")), None)
                if deleted_row is None:
                    raise ShortcutError("This shortcut no longer exists. Refresh the list.")
                updated = [row for row in rows if row["id"] != deleted_row["id"]]
                self.commit(updated, rows, deleted_row=deleted_row)
            elif operation == "undo-delete":
                if self.deleted_row is None:
                    raise ShortcutError("There is no deleted shortcut to restore.")
                if len(rows) >= 200:
                    raise ShortcutError("Cannot restore: maximum 200 shortcuts reached.")
                row = dict(self.deleted_row)
                if any(item["id"] == row["id"] for item in rows):
                    raise ShortcutError("Cannot restore: the shortcut identifier is already in use.")
                conflicts = self.conflicts(row, rows, binds) if row.get("enabled", True) else []
                if conflicts:
                    row["enabled"] = False
                self.commit(rows + [row], rows, deleted_row=None)
                details = {"restoredDisabled": bool(conflicts), "undoConflicts": conflicts}
            elif operation == "enable":
                enabled = request.get("enabled")
                if not isinstance(enabled, bool):
                    raise ShortcutError("Enabled state must be true or false.")
                row = next((item for item in rows if item["id"] == request.get("id")), None)
                if not row:
                    raise ShortcutError("This shortcut no longer exists. Refresh the list.")
                updated_row = {**row, "enabled": enabled}
                self.check_row(updated_row)
                if enabled:
                    conflicts = self.conflicts(updated_row, rows, binds)
                    if conflicts:
                        raise ShortcutError("Conflict: " + "; ".join(conflicts))
                self.commit([updated_row if item["id"] == row["id"] else item for item in rows], rows)
            elif operation == "pause":
                if not isinstance(request.get("paused"), bool):
                    raise ShortcutError("Pause state must be true or false.")
                self.commit(rows, rows, request["paused"])
            elif operation in ("preview-import", "import"):
                added, skipped, digest = self.import_rows(request.get("path"), rows)
                if operation == "preview-import":
                    return {"ok": True, "added": len(added), "skipped": skipped, "importHash": digest}
                if request.get("importHash") != digest:
                    raise ShortcutError("The import file changed. Preview it again before importing.")
                if not added:
                    raise ShortcutError("There are no new shortcuts to import.")
                details = {"imported": len(added), "skipped": skipped, "backup": self.commit(rows + added, rows)}
            elif operation == "export":
                details = {"exportPath": self.export_rows(request, rows)}
            rows, revision = self.load()
            binds = self.binds()
            return {
                "ok": True, "shortcuts": rows, "revision": revision,
                "paused": self.paused, "canUndoDelete": self.deleted_row is not None, **details,
                "activeCount": len(binds),
                "existing": [{
                    "shortcut": " + ".join(
                        [mod for mod, bit in MODIFIERS.items() if bind["modmask"] & bit]
                        + [f"code:{bind['keycode']}" if bind.get("keycode") else bind["key"]]
                    ),
                    "name": str(bind.get("description") or bind.get("dispatcher") or "")[:300],
                    "submap": str(bind.get("submap", ""))[:120],
                } for bind in binds[:2000]],
            }

    def type_text(self, identifier):
        with (self.directory / "lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            rows, _ = self.load()
            row = next((row for row in rows if row["id"] == identifier), None)
            if not row or row.get("type") != "text" or not row.get("enabled", True) or self.paused:
                raise ShortcutError("This text shortcut no longer exists.")
            text = row["text"]
        with (self.directory / "typing.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ShortcutError("Another text shortcut is still typing.") from error
            self.wait_for_modifiers()
            with (self.directory / "lock").open("a") as state_lock:
                fcntl.flock(state_lock, fcntl.LOCK_SH)
                current, _ = self.load()
                if self.paused or not any(
                    item["id"] == identifier and item.get("enabled", True)
                    and item.get("type") == "text" and item["text"] == text for item in current
                ):
                    raise ShortcutError("The text shortcut changed or was disabled before typing.")
            # Stdin keeps literal text out of shell parsing, option parsing and argv.
            result = self.runner(
                ["wtype", "-"], input=text, capture_output=True, text=True,
                timeout=15, check=False,
            )
            if result.returncode:
                raise ShortcutError(f"Typing failed: {result.stderr.strip() or 'wtype exited unsuccessfully'}")

    def wait_for_modifiers(self):
        deadline = time.monotonic() + 5
        while True:
            state = self.hypr("repl", MODIFIER_QUERY)
            if state == "false":
                return
            if state != "true":
                raise ShortcutError("Cannot read keyboard state; text was not typed.")
            if time.monotonic() >= deadline:
                raise ShortcutError("Release the shortcut modifiers before typing text.")
            time.sleep(0.02)


def main():
    typing = len(sys.argv) > 1 and sys.argv[1] == "type"
    try:
        if typing:
            if len(sys.argv) != 3:
                raise ShortcutError("Usage: shortcuts.py type <shortcut-id>")
            Store().type_text(sys.argv[2])
            return 0
        raw = sys.stdin.read(32769)
        if len(raw) > 32768:
            raise ShortcutError("Request too large.")
        result = Store().handle(json.loads(raw))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ShortcutError, OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
        if typing:
            print(f"OmaHotkeys: {error}", file=sys.stderr)
            try:
                subprocess.run(
                    ["notify-send", "OmaHotkeys", "Text shortcut failed. Check the session logs for details."],
                    timeout=5, check=True,
                )
            except (OSError, subprocess.SubprocessError) as notification_error:
                print(f"OmaHotkeys: notification failed: {notification_error}", file=sys.stderr)
            return 1
        print(json.dumps({"ok": False, "error": str(error)[:2000]}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
