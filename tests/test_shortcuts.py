import importlib.util
import json
from pathlib import Path
from unittest.mock import patch
import re
import subprocess
import tempfile
import stat
import unittest
import uuid


SPEC = importlib.util.spec_from_file_location(
    "shortcuts", Path(__file__).parents[1] / "bin/shortcuts.py",
)
shortcuts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(shortcuts)


def row(shortcut="SUPER + F10", name="Test", command="true"):
    return {
        "id": str(uuid.uuid4()), "name": name,
        "shortcut": shortcut, "command": command,
    }


def binding(shortcut="SUPER + F10", name="Native", **extra):
    mask, _, canonical = shortcuts.Keysyms().parse(shortcut)
    return {
        "modmask": mask, "key": canonical.split(" + ")[-1],
        "keycode": 0, "description": name, "dispatcher": "__lua",
        "submap": "", **extra,
    }


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = shortcuts.Store(self.temporary.name, self.run_hypr)
        self.store.directory.mkdir(parents=True)
        self.store.lua.parent.mkdir(parents=True)
        self.native = []
        self.fail_reload = False
        self.inject_conflict = False
        self.set_rows([])

    def set_rows(self, rows, *, paused=False, deleted=None):
        payload = {"version": 1, "shortcuts": rows}
        if paused:
            payload["paused"] = True
        if deleted is not None:
            payload["deleted"] = deleted
        self.store.data.write_text(json.dumps(payload))
        self.store.lua.write_bytes(shortcuts.render(rows, paused))

    def run_hypr(self, command, **kwargs):
        action = command[-1]
        text = self.store.lua.read_text()
        if action == "reload":
            if self.inject_conflict and "o.bind(" in text:
                self.native = [binding()]
            return subprocess.CompletedProcess(command, 0, "ok", "")
        if action == "configerrors":
            errors = "invalid configuration" if self.fail_reload and "FAIL" in text else ""
            return subprocess.CompletedProcess(command, 0, errors, "")
        if action == "binds":
            binds = list(self.native)
            quoted = r'("(?:[^"\\]|\\.)*")'
            for match in re.finditer(
                rf"^o.bind\({quoted}, {quoted}, {quoted}(, \{{ release = true \}})?\)$", text, re.MULTILINE,
            ):
                keys, name, _ = (json.loads(value) for value in match.groups()[:3])
                binds.append(binding(keys, name, release=bool(match[4])))
            text = ""
            for bind in binds:
                text += "bindrd\n" if bind.get("release") else "bindd\n"
                for key in ("modmask", "key", "keycode", "description", "dispatcher", "submap"):
                    text += f"\t{key}: {bind[key]}\n"
                text += "\targ: 1\n\tcatchall: false\n\n"
            return subprocess.CompletedProcess(command, 0, text, "")
        raise AssertionError(command)

    def request(self, operation, value=None):
        return {
            "operation": operation, "revision": self.store.load()[1],
            **(value or {}),
        }

    def test_create_edit_delete_and_reload(self):
        created = self.store.handle(self.request("save", {
            "name": "My command", "shortcut": "WIN + Control + f10", "command": "true",
        }))
        saved = created["shortcuts"][0]
        self.assertEqual(saved["shortcut"], "CTRL + SUPER + F10")
        edited = self.store.handle(self.request("save", {**saved, "command": "printf hello"}))
        self.assertEqual(edited["shortcuts"][0]["command"], "printf hello")
        result = self.store.handle(self.request("delete", {"id": saved["id"]}))
        self.assertEqual(result["shortcuts"], [])
        self.assertNotIn("o.bind(", self.store.lua.read_text())

    def test_undo_deletion_persists_across_restart_and_restores_identity(self):
        saved = row(name="Restore me", command="printf original")
        self.set_rows([saved])
        deleted = self.store.handle(self.request("delete", {"id": saved["id"]}))
        self.assertTrue(deleted["canUndoDelete"])
        self.assertEqual(deleted["shortcuts"], [])
        self.assertEqual(json.loads(self.store.data.read_text())["deleted"], saved)
        restarted = shortcuts.Store(self.temporary.name, self.run_hypr)
        self.assertTrue(restarted.handle({"operation": "list"})["canUndoDelete"])
        restored = restarted.handle({
            "operation": "undo-delete", "revision": restarted.load()[1],
        })
        self.assertEqual(restored["shortcuts"], [saved])
        self.assertFalse(restored["canUndoDelete"])
        self.assertFalse(restored["restoredDisabled"])
        self.assertNotIn("deleted", json.loads(self.store.data.read_text()))
        self.assertIn(shortcuts.description(saved), self.store.lua.read_text())
        with self.assertRaisesRegex(shortcuts.ShortcutError, "no deleted shortcut"):
            restarted.handle({"operation": "undo-delete", "revision": restarted.load()[1]})

    def test_undo_restores_disabled_when_native_or_managed_keys_are_taken(self):
        for native in (True, False):
            with self.subTest(native=native):
                saved = row()
                self.native = []
                self.set_rows([saved])
                self.store.handle(self.request("delete", {"id": saved["id"]}))
                if native:
                    self.native = [binding(name="New native shortcut")]
                else:
                    self.store.handle(self.request("save", {
                        "name": "New managed shortcut", "shortcut": saved["shortcut"], "command": "true",
                    }))
                restored = self.store.handle(self.request("undo-delete"))
                result = next(item for item in restored["shortcuts"] if item["id"] == saved["id"])
                self.assertEqual(result, {**saved, "enabled": False})
                self.assertTrue(restored["restoredDisabled"])
                self.assertTrue(restored["undoConflicts"])
                self.assertNotIn(shortcuts.description(saved), self.store.lua.read_text())
                self.assertEqual(self.store.lua.read_text().count("o.bind("), 0 if native else 1)

    def test_undo_preserves_pause_and_individual_disabled_state(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                saved = {**row(), "enabled": enabled}
                self.set_rows([saved], paused=True)
                self.store.handle(self.request("delete", {"id": saved["id"]}))
                restored = self.store.handle(self.request("undo-delete"))
                self.assertEqual(restored["shortcuts"], [saved])
                self.assertTrue(restored["paused"])
                self.assertNotIn("o.bind(", self.store.lua.read_text())

    def test_only_latest_deletion_can_be_undone(self):
        first, second = row(), row("SUPER + F11")
        self.set_rows([first, second])
        self.store.handle(self.request("delete", {"id": first["id"]}))
        self.store.handle(self.request("delete", {"id": second["id"]}))
        restored = self.store.handle(self.request("undo-delete"))
        self.assertEqual(restored["shortcuts"], [second])
        self.assertFalse(restored["canUndoDelete"])

    def test_other_changes_keep_undo_and_exports_exclude_deleted_values(self):
        saved = row(command="printf deleted-private-value")
        self.set_rows([saved])
        self.store.handle(self.request("delete", {"id": saved["id"]}))
        self.store.handle(self.request("save", {
            "name": "Other", "shortcut": "SUPER + F11", "command": "true",
        }))
        self.store.handle(self.request("pause", {"paused": True}))
        path = Path(self.temporary.name) / "export.json"
        result = self.store.handle(self.request("export", {"path": str(path), "confirmed": True}))
        self.assertTrue(result["canUndoDelete"])
        self.assertNotIn(saved["command"], path.read_text())
        self.assertNotIn("deleted", json.loads(path.read_text()))
        restored = self.store.handle(self.request("undo-delete"))
        self.assertIn(saved, restored["shortcuts"])
        self.assertTrue(restored["paused"])

    def test_stale_undo_cannot_overwrite_newer_changes(self):
        saved = row()
        self.set_rows([saved])
        self.store.handle(self.request("delete", {"id": saved["id"]}))
        stale = self.request("undo-delete")
        self.store.handle(self.request("pause", {"paused": True}))
        before = self.store.data.read_bytes(), self.store.lua.read_bytes()
        with self.assertRaisesRegex(shortcuts.ShortcutError, "another window"):
            self.store.handle(stale)
        self.assertEqual(before, (self.store.data.read_bytes(), self.store.lua.read_bytes()))
        self.assertTrue(self.store.handle({"operation": "list"})["canUndoDelete"])

    def test_failed_undo_keeps_record_available_for_retry(self):
        saved = row(command="FAIL")
        self.set_rows([saved])
        self.store.handle(self.request("delete", {"id": saved["id"]}))
        before = self.store.data.read_bytes(), self.store.lua.read_bytes()
        self.fail_reload = True
        with self.assertRaisesRegex(shortcuts.ShortcutError, "previous shortcuts restored"):
            self.store.handle(self.request("undo-delete"))
        self.assertEqual(before, (self.store.data.read_bytes(), self.store.lua.read_bytes()))
        self.assertTrue(self.store.handle({"operation": "list"})["canUndoDelete"])
        self.fail_reload = False
        self.assertEqual(self.store.handle(self.request("undo-delete"))["shortcuts"], [saved])

    def test_failed_delete_preserves_previous_undo_record(self):
        deleted, remaining = row(), row("SUPER + F11")
        self.set_rows([deleted, remaining])
        self.store.handle(self.request("delete", {"id": deleted["id"]}))
        before = self.store.data.read_bytes(), self.store.lua.read_bytes()
        with patch.object(self.store, "verify", side_effect=shortcuts.ShortcutError("Verification failed")):
            with self.assertRaisesRegex(shortcuts.ShortcutError, "previous shortcuts restored"):
                self.store.handle(self.request("delete", {"id": remaining["id"]}))
        self.assertEqual(before, (self.store.data.read_bytes(), self.store.lua.read_bytes()))
        self.assertEqual(self.store.handle(self.request("undo-delete"))["shortcuts"], [remaining, deleted])

    def test_undo_text_requires_runtime_only_when_enabled(self):
        saved = {**row(), "type": "text", "text": "Literal $HOME; <b>text</b>\n\t"}
        del saved["command"]
        self.set_rows([], deleted=saved)
        before = self.store.data.read_bytes(), self.store.lua.read_bytes()
        with patch.object(shortcuts.shutil, "which", return_value=None):
            self.assertTrue(self.store.handle({"operation": "list"})["canUndoDelete"])
            with self.assertRaisesRegex(shortcuts.ShortcutError, "require wtype"):
                self.store.handle(self.request("undo-delete"))
        self.assertEqual(before, (self.store.data.read_bytes(), self.store.lua.read_bytes()))
        saved["enabled"] = False
        self.set_rows([], deleted=saved)
        with patch.object(shortcuts.shutil, "which", return_value=None):
            restored = self.store.handle(self.request("undo-delete"))
        self.assertEqual(restored["shortcuts"], [saved])
        self.assertNotIn("o.bind(", self.store.lua.read_text())

    def test_undo_capacity_and_identifier_errors_keep_deleted_record(self):
        saved = row()
        cases = (
            ([{**row("SUPER + F11"), "enabled": False} for _ in range(200)], "maximum 200"),
            ([saved], "identifier is already in use"),
        )
        for rows, message in cases:
            with self.subTest(message=message):
                self.set_rows(rows, deleted=saved)
                before = self.store.data.read_bytes(), self.store.lua.read_bytes()
                with self.assertRaisesRegex(shortcuts.ShortcutError, message):
                    self.store.handle(self.request("undo-delete"))
                self.assertEqual(before, (self.store.data.read_bytes(), self.store.lua.read_bytes()))
                self.assertTrue(self.store.handle({"operation": "list"})["canUndoDelete"])

    def test_native_and_custom_conflicts_and_modifier_order(self):
        self.native = [binding("CTRL + SUPER + F10", "User custom")]
        result = self.store.handle(self.request("validate", {
            "name": "Test", "shortcut": "super + control + f10", "command": "true",
        }))
        self.assertFalse(result["valid"])
        self.assertEqual(result["conflicts"], ["User custom"])
        with self.assertRaisesRegex(shortcuts.ShortcutError, "Conflict"):
            self.store.handle(self.request("save", {
                "name": "Test", "shortcut": "SUPER + CTRL + F10", "command": "true",
            }))
        self.assertEqual(self.store.load()[0], [])

    def test_alias_and_case_conflicts(self):
        self.native = [binding("SUPER + Escape")]
        candidate = row("SUPER + esc")
        self.assertEqual(self.store.conflicts(candidate, [], self.native), ["Native"])
        self.native = [binding("SUPER + A")]
        self.assertEqual(self.store.conflicts(row("SUPER + a"), [], self.native), ["Native"])

    def test_edit_excludes_only_itself(self):
        own, other = row(), row("SUPER + F11", "Other")
        self.set_rows([own, other])
        self.assertTrue(self.store.handle(self.request("validate", own))["valid"])
        result = self.store.handle(self.request("validate", {**own, "shortcut": other["shortcut"]}))
        self.assertFalse(result["valid"])
        self.assertIn(shortcuts.description(other), result["conflicts"])
        self.native = [binding(name="Unrelated duplicate")]
        self.assertFalse(self.store.handle(self.request("validate", own))["valid"])

    def test_submap_release_and_physical_key_are_not_assumed_safe(self):
        for extra in ({"submap": "resize"}, {"release": True}, {"keycode": 76}):
            with self.subTest(extra=extra):
                self.assertTrue(self.store.conflicts(row(), [], [binding(**extra)]))
        self.assertTrue(self.store.conflicts(row(), [], [binding(catch_all=True, key="")]))

    def test_physical_keycodes_resolve_without_blocking_unrelated_keys(self):
        symbols = self.store.keys.physical_symbols({
            "rules": "", "model": "", "layout": "us", "variant": "", "options": "",
        }, {10})
        physical = binding("SUPER + 1", key="", keycode=10, symbols=symbols[10])
        self.assertTrue(self.store.conflicts(row("SUPER + 1"), [], [physical]))
        self.assertFalse(self.store.conflicts(row("SUPER + F10"), [], [physical]))

    def test_mouse_bindings_do_not_block_keyboard_shortcuts(self):
        self.assertFalse(self.store.conflicts(row(), [], [
            binding(key="mouse:272", mouse=True),
            binding(key="mouse_down", mouse=True),
        ]))

    def test_ignore_modifiers_binding_conflicts_with_modified_key(self):
        self.assertTrue(self.store.conflicts(row(), [], [
            binding("F10", "Ignore modifiers", ignore_mods=True),
        ]))

    def test_invalid_input_is_rejected(self):
        for keys in ("SUPER + SUPER + F10", "SUPER +", "MAGIC + F10", "SUPER + NotARealKey"):
            with self.subTest(keys=keys), self.assertRaises(shortcuts.ShortcutError):
                self.store.check_row(row(keys))
        for command in ("true\nos.execute('bad')", "", 123):
            with self.subTest(command=command), self.assertRaises(shortcuts.ShortcutError):
                self.store.handle(self.request("validate", {
                    "name": "Test", "shortcut": "SUPER + F10", "command": command,
                }))

    def test_stale_revision_cannot_overwrite(self):
        request = self.request("save", {"name": "Test", "shortcut": "SUPER + F10", "command": "true"})
        self.set_rows([row("SUPER + F11")])
        with self.assertRaisesRegex(shortcuts.ShortcutError, "another window"):
            self.store.handle(request)
        self.assertEqual(len(self.store.load()[0]), 1)

    def test_invalid_reload_rolls_back_data_and_lua(self):
        before = self.store.data.read_bytes(), self.store.lua.read_bytes()
        self.fail_reload = True
        with self.assertRaisesRegex(shortcuts.ShortcutError, "previous shortcuts restored"):
            self.store.handle(self.request("save", {
                "name": "Test", "shortcut": "SUPER + F10", "command": "FAIL",
            }))
        self.assertEqual(before, (self.store.data.read_bytes(), self.store.lua.read_bytes()))

    def test_conflict_appearing_during_reload_rolls_back(self):
        self.inject_conflict = True
        with self.assertRaisesRegex(shortcuts.ShortcutError, "previous shortcuts restored"):
            self.store.handle(self.request("save", {
                "name": "Test", "shortcut": "SUPER + F10", "command": "true",
            }))
        self.assertEqual(self.store.load()[0], [])

    def test_external_lua_edit_is_not_overwritten(self):
        self.store.lua.write_text("-- external change\n")
        with self.assertRaisesRegex(shortcuts.ShortcutError, "outside OmaHotkeys"):
            self.store.handle({"operation": "list"})
        self.assertEqual(self.store.lua.read_text(), "-- external change\n")

    def test_markup_and_lua_shaped_input_remain_literal(self):
        value = row(name='<img src="https://example.invalid/tracker">', command='printf \'"); os.execute("false"); --\'')
        self.store.handle(self.request("save", {key: item for key, item in value.items() if key != "id"}))
        saved = self.store.load()[0][0]
        self.assertEqual(saved["name"], value["name"])
        self.assertEqual(saved["command"], value["command"])
        # Execute the generated Lua only with a recording stub, never a dispatcher.
        result = subprocess.run(
            ["lua", "-"], input="local count = 0\n"
            "o = { bind = function(keys, name, command) count = count + 1 end }\n"
            + self.store.lua.read_text() + "\nassert(count == 1)\n",
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_text_create_edit_conflicts_and_conversion(self):
        text = '  <b>sample@example.invalid</b> $(echo never)\nSecond line\t  '
        created = self.store.handle(self.request("save", {
            "name": "Text", "shortcut": "SUPER + F10", "type": "text", "text": text,
        }))
        saved = created["shortcuts"][0]
        self.assertEqual(saved["text"], text)
        self.assertNotIn("command", saved)
        self.assertNotIn(text, self.store.lua.read_text())
        self.assertTrue(self.store.handle(self.request("validate", saved))["valid"])
        self.native = [binding("SUPER + F11")]
        self.assertFalse(self.store.handle(self.request("validate", {
            **saved, "shortcut": "SUPER + F11",
        }))["valid"])
        edited = self.store.handle(self.request("save", {**saved, "text": "Updated"}))
        self.assertEqual(edited["shortcuts"][0]["text"], "Updated")
        converted = self.store.handle(self.request("save", {
            **saved, "type": "command", "command": "true",
        }))
        self.assertNotIn("text", converted["shortcuts"][0])
        self.assertNotIn("release = true", self.store.lua.read_text())

    def test_typing_uses_stdin_without_shell_or_clipboard(self):
        text = '-M ctrl -- $(echo never); "quotes" é\nNext\t '
        saved = {**row(), "type": "text", "text": text}
        self.set_rows([saved])
        with patch.object(self.store, "wait_for_modifiers"), patch.object(self.store, "runner") as runner:
            runner.return_value = subprocess.CompletedProcess(["wtype", "-"], 0, "", "")
            self.store.type_text(saved["id"])
        runner.assert_called_once_with(
            ["wtype", "-"], input=text, capture_output=True, text=True,
            timeout=15, check=False,
        )
        with self.assertRaisesRegex(shortcuts.ShortcutError, "no longer exists"):
            self.store.type_text(str(uuid.uuid4()))

    def test_text_errors_are_reported_and_legacy_commands_still_load(self):
        legacy = row()
        self.set_rows([legacy])
        self.assertEqual(self.store.load()[0], [legacy])
        for value in ("", "x" * 2049, "hello\0", "hello\r", 42):
            with self.subTest(value=value), self.assertRaises(shortcuts.ShortcutError):
                self.store.handle(self.request("validate", {
                    "name": "Text", "shortcut": "SUPER + F10", "type": "text", "text": value,
                }))
        saved = {**row(), "type": "text", "text": "Test"}
        self.set_rows([saved])
        with patch.object(self.store, "wait_for_modifiers"), patch.object(self.store, "runner") as runner:
            runner.return_value = subprocess.CompletedProcess(["wtype", "-"], 1, "", "No virtual keyboard")
            with self.assertRaisesRegex(shortcuts.ShortcutError, "Typing failed"):
                self.store.type_text(saved["id"])
        with patch.object(shortcuts.shutil, "which", return_value=None):
            with self.assertRaisesRegex(shortcuts.ShortcutError, "require wtype"):
                self.store.check_row(saved)

    def test_typing_waits_for_modifier_release_and_rejects_unknown_state(self):
        with patch.object(self.store, "hypr", side_effect=["true", "false"]) as query, patch.object(shortcuts.time, "sleep"):
            self.store.wait_for_modifiers()
        self.assertEqual(query.call_count, 2)
        with patch.object(self.store, "hypr", return_value="unknown"):
            with self.assertRaisesRegex(shortcuts.ShortcutError, "not typed"):
                self.store.wait_for_modifiers()
        with patch.object(self.store, "hypr", return_value="true"), patch.object(
            shortcuts.time, "monotonic", side_effect=[0, 6],
        ):
            with self.assertRaisesRegex(shortcuts.ShortcutError, "Release"):
                self.store.wait_for_modifiers()

    def test_enable_disable_keeps_saved_record_and_rechecks_conflicts(self):
        created = self.store.handle(self.request("save", {
            "name": "Toggle", "shortcut": "SUPER + F10", "command": "true",
        }))
        saved = created["shortcuts"][0]
        disabled = self.store.handle(self.request("enable", {"id": saved["id"], "enabled": False}))
        self.assertFalse(disabled["shortcuts"][0]["enabled"])
        self.assertNotIn("o.bind(", self.store.lua.read_text())
        self.native = [binding(name="New native binding")]
        before = self.store.data.read_bytes(), self.store.lua.read_bytes()
        with self.assertRaisesRegex(shortcuts.ShortcutError, "Conflict"):
            self.store.handle(self.request("enable", {"id": saved["id"], "enabled": True}))
        self.assertEqual(before, (self.store.data.read_bytes(), self.store.lua.read_bytes()))
        self.native = []
        self.store.handle(self.request("enable", {"id": saved["id"], "enabled": True}))
        self.assertIn("o.bind(", self.store.lua.read_text())
        self.assertFalse(self.store.handle(self.request("save", {**saved, "enabled": False}))["shortcuts"][0]["enabled"])

    def test_pause_resume_preserves_individual_states_and_rolls_back_on_conflict(self):
        enabled, disabled = row(), {**row("SUPER + F11"), "enabled": False}
        self.set_rows([enabled, disabled])
        paused = self.store.handle(self.request("pause", {"paused": True}))
        self.assertTrue(paused["paused"])
        self.assertEqual(paused["shortcuts"], [enabled, disabled])
        self.assertNotIn("o.bind(", self.store.lua.read_text())
        self.assertTrue(self.store.handle({"operation": "list"})["paused"])
        self.native = [binding()]
        with self.assertRaisesRegex(shortcuts.ShortcutError, "previous shortcuts restored"):
            self.store.handle(self.request("pause", {"paused": False}))
        self.assertTrue(self.store.handle({"operation": "list"})["paused"])
        self.assertNotIn("o.bind(", self.store.lua.read_text())
        self.native = []
        resumed = self.store.handle(self.request("pause", {"paused": False}))
        self.assertFalse(resumed["paused"])
        self.assertEqual(self.store.lua.read_text().count("o.bind("), 1)

    def test_disabled_rows_can_conflict_without_reserving_keys(self):
        disabled = {**row(), "enabled": False}
        self.set_rows([disabled])
        candidate = {key: value for key, value in row().items() if key != "id"}
        self.assertTrue(self.store.handle(self.request("validate", candidate))["valid"])
        self.native = [binding()]
        validation = self.store.handle(self.request("validate", disabled))
        self.assertTrue(validation["valid"])
        self.assertTrue(validation["conflicts"])
        self.store.handle(self.request("save", disabled))
        self.assertNotIn("o.bind(", self.store.lua.read_text())
        for value in (0, "yes", None):
            with self.subTest(value=value), self.assertRaises(shortcuts.ShortcutError):
                self.store.handle(self.request("enable", {"id": disabled["id"], "enabled": value}))

    def export(self, rows):
        self.set_rows(rows)
        path = Path(self.temporary.name) / "export.json"
        result = self.store.handle(self.request("export", {"path": str(path), "confirmed": True}))
        self.assertEqual(result["exportPath"], str(path))
        return path

    def test_export_requires_warning_confirmation_and_cannot_overwrite_config(self):
        saved = {**row(), "type": "text", "text": "  é literal\nText  "}
        self.set_rows([saved])
        path = Path(self.temporary.name) / "export.json"
        with self.assertRaisesRegex(shortcuts.ShortcutError, "Confirm"):
            self.store.handle(self.request("export", {"path": str(path)}))
        self.assertFalse(path.exists())
        path = self.export([saved])
        self.assertEqual(json.loads(path.read_text())["shortcuts"], [saved])
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        with self.assertRaisesRegex(shortcuts.ShortcutError, "already exists"):
            self.store.handle(self.request("export", {"path": str(path), "confirmed": True}))
        for target in (self.store.data, self.store.lua, self.store.directory / "ui.ini"):
            with self.subTest(target=target), self.assertRaisesRegex(shortcuts.ShortcutError, "cannot overwrite"):
                self.store.handle(self.request("export", {
                    "path": str(target), "confirmed": True, "overwrite": True,
                }))

    def test_export_browser_selects_a_literal_path_without_exporting_or_locking_data(self):
        destination = Path(self.temporary.name) / "é space; not-a-command.json"
        before = self.store.data.read_bytes(), self.store.lua.read_bytes()
        with patch.object(shortcuts.shutil, "which", return_value="/usr/bin/zenity"), patch.object(
            self.store, "runner", return_value=subprocess.CompletedProcess(
                ["zenity"], 0, str(destination) + "\n", "",
            ),
        ) as runner, patch.object(shortcuts.fcntl, "flock") as lock:
            response = self.store.handle({
                "operation": "choose-export", "path": str(destination),
                "title": "Export OmaHotkeys shortcuts", "filterLabel": "JSON files",
            })
        self.assertEqual(response, {"ok": True, "path": str(destination)})
        command = runner.call_args.args[0]
        self.assertEqual(command[0], "zenity")
        self.assertIn("--save", command)
        self.assertIn("--filename=" + str(destination), command)
        self.assertNotIn("shell", runner.call_args.kwargs)
        lock.assert_not_called()
        self.assertFalse(destination.exists())
        self.assertEqual(before, (self.store.data.read_bytes(), self.store.lua.read_bytes()))

    def test_import_browser_selects_existing_file_without_importing(self):
        selected = Path(self.temporary.name) / "another folder" / "é shortcuts.json"
        selected.parent.mkdir()
        selected.write_text(json.dumps({"version": 1, "shortcuts": [row()]}))
        before = self.store.data.read_bytes(), self.store.lua.read_bytes()
        with patch.object(shortcuts.shutil, "which", return_value="/usr/bin/zenity"), patch.object(
            self.store, "runner", return_value=subprocess.CompletedProcess(["zenity"], 0, str(selected) + "\n", ""),
        ) as runner, patch.object(shortcuts.fcntl, "flock") as lock:
            response = self.store.handle({"operation": "choose-import", "path": str(selected)})
        self.assertEqual(response, {"ok": True, "path": str(selected)})
        self.assertNotIn("--save", runner.call_args.args[0])
        lock.assert_not_called()
        self.assertEqual(before, (self.store.data.read_bytes(), self.store.lua.read_bytes()))

    def test_import_browser_rejects_missing_file_or_directory(self):
        request = {"operation": "choose-import", "path": str(Path(self.temporary.name) / "input.json")}
        with patch.object(shortcuts.shutil, "which", return_value="/usr/bin/zenity"), patch.object(self.store, "runner") as runner:
            for path in (request["path"], self.temporary.name):
                runner.return_value = subprocess.CompletedProcess(["zenity"], 0, path + "\n", "")
                with self.subTest(path=path), self.assertRaisesRegex(shortcuts.ShortcutError, "existing JSON file"):
                    self.store.handle(request)

    def test_file_browser_cancel_error_and_invalid_selection(self):
        for operation in ("choose-import", "choose-export"):
            request = {"operation": operation, "path": str(Path(self.temporary.name) / "export.json")}
            with self.subTest(operation=operation), patch.object(
                shortcuts.shutil, "which", return_value="/usr/bin/zenity",
            ), patch.object(self.store, "runner") as runner:
                runner.return_value = subprocess.CompletedProcess(["zenity"], 1, "", "")
                self.assertEqual(self.store.handle(request), {"ok": True, "cancelled": True})
                runner.return_value = subprocess.CompletedProcess(["zenity"], 2, "", "Cannot open display")
                with self.assertRaisesRegex(shortcuts.ShortcutError, "Cannot open display"):
                    self.store.handle(request)
                runner.return_value = subprocess.CompletedProcess(["zenity"], 0, "", "")
                with self.assertRaisesRegex(shortcuts.ShortcutError, "local JSON file"):
                    self.store.handle(request)

    def test_file_browser_missing_tool_is_reported(self):
        with patch.object(shortcuts.shutil, "which", return_value=None):
            for operation in ("choose-import", "choose-export"):
                with self.subTest(operation=operation), self.assertRaisesRegex(shortcuts.ShortcutError, "omarchy pkg add zenity"):
                    self.store.handle({"operation": operation})

    def test_import_adds_disabled_skips_duplicates_and_never_replaces(self):
        existing = row("SUPER + F10", "Existing")
        # A colliding identifier is remapped, not used to overwrite a saved row.
        text = {**row("SUPER + F10", '<img src="https://example.invalid">'),
                "id": existing["id"], "type": "text", "text": "é  \n", "enabled": True}
        path = Path(self.temporary.name) / "import.json"
        path.write_text(json.dumps({"format": "OmaHotkeys", "version": 1, "shortcuts": [existing, text, text]}))
        self.set_rows([existing])
        self.native = [binding("SUPER + F12")]
        preview = self.store.handle({"operation": "preview-import", "path": path.as_uri()})
        self.assertEqual((preview["added"], preview["skipped"]), (1, 2))
        before = self.store.data.read_bytes()
        result = self.store.handle(self.request("import", {
            "path": str(path), "importHash": preview["importHash"],
        }))
        self.assertEqual(result["shortcuts"][0], existing)
        imported = result["shortcuts"][1]
        self.assertNotEqual(imported["id"], existing["id"])
        self.assertFalse(imported["enabled"])
        self.assertEqual(imported["text"], text["text"])
        self.assertEqual(imported["name"], text["name"])
        self.assertEqual(Path(result["backup"]).read_bytes(), before)
        self.assertEqual(self.store.lua.read_text().count("o.bind("), 1)
        again = self.store.handle({"operation": "preview-import", "path": str(path)})
        self.assertEqual(again["added"], 0)
        self.assertEqual(again["skipped"], 3)

    def test_import_changed_file_or_stale_revision_cannot_commit(self):
        path = self.export([row("SUPER + F11")])
        self.set_rows([])
        preview = self.store.handle({"operation": "preview-import", "path": str(path)})
        request = self.request("import", {"path": str(path), "importHash": preview["importHash"]})
        path.write_text(json.dumps({"version": 1, "shortcuts": []}))
        with self.assertRaisesRegex(shortcuts.ShortcutError, "file changed"):
            self.store.handle(request)
        self.assertEqual(self.store.load()[0], [])
        self.set_rows([row()])
        with self.assertRaisesRegex(shortcuts.ShortcutError, "another window"):
            self.store.handle(request)

    def test_import_invalid_and_oversized_files_do_not_change_state(self):
        path = Path(self.temporary.name) / "bad.json"
        before = self.store.data.read_bytes(), self.store.lua.read_bytes()
        payloads = (
            {"version": True, "shortcuts": []}, {"version": 2, "shortcuts": []},
            {"version": 1, "shortcuts": [None]}, {"version": 1, "shortcuts": [row(command="bad\ncommand")]},
            {"version": 1, "shortcuts": [{**row(), "enabled": "yes"}]},
            {"version": 1, "shortcuts": [row()] * 201},
        )
        for payload in payloads:
            path.write_text(json.dumps(payload))
            with self.subTest(payload=payload), self.assertRaises(shortcuts.ShortcutError):
                self.store.handle({"operation": "preview-import", "path": str(path)})
        path.write_bytes(b" " * (1024 * 1024 + 1))
        with self.assertRaisesRegex(shortcuts.ShortcutError, "too large"):
            self.store.handle({"operation": "preview-import", "path": str(path)})
        self.assertEqual(before, (self.store.data.read_bytes(), self.store.lua.read_bytes()))

    def test_backups_are_private_and_retain_latest_ten(self):
        directory = self.store.directory / "backups"
        directory.mkdir()
        unrelated = directory / "backup-user.json"
        unrelated.write_text("Keep")
        for index in range(12):
            self.store.backup(json.dumps({"snapshot": index}).encode())
        paths = sorted(path for path in directory.iterdir() if path != unrelated)
        self.assertEqual(len(paths), 10)
        self.assertEqual(json.loads(paths[0].read_text())["snapshot"], 2)
        self.assertTrue(all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in paths))
        self.assertEqual(unrelated.read_text(), "Keep")

    def test_multibyte_state_limit_is_checked_before_writes(self):
        rows = [{**row(), "type": "text", "text": "🎹" * 2048, "enabled": False} for _ in range(150)]
        before = self.store.data.read_bytes(), self.store.lua.read_bytes()
        with self.assertRaisesRegex(shortcuts.ShortcutError, "1 MiB"):
            self.store.commit(rows, [])
        self.assertEqual(before, (self.store.data.read_bytes(), self.store.lua.read_bytes()))

    def test_new_export_is_atomic_and_does_not_leave_partial_files_on_failure(self):
        path = Path(self.temporary.name) / "export.json"
        with patch.object(shortcuts.os, "link", side_effect=OSError("Write failed")):
            with self.assertRaisesRegex(OSError, "Write failed"):
                self.store.handle(self.request("export", {"path": str(path), "confirmed": True}))
        self.assertFalse(path.exists())
        self.assertEqual(sorted(item.name for item in path.parent.iterdir()), ["hypr", "omarchy"])

    def test_disabled_or_paused_text_cannot_type(self):
        saved = {**row(), "type": "text", "text": "Test", "enabled": False}
        self.set_rows([saved])
        with self.assertRaisesRegex(shortcuts.ShortcutError, "no longer exists"):
            self.store.type_text(saved["id"])
        saved["enabled"] = True
        self.set_rows([saved])
        self.store.handle(self.request("pause", {"paused": True}))
        with self.assertRaisesRegex(shortcuts.ShortcutError, "no longer exists"):
            self.store.type_text(saved["id"])

    def test_text_disabled_while_waiting_does_not_type(self):
        saved = {**row(), "type": "text", "text": "Test"}
        self.set_rows([saved])
        with patch.object(self.store, "wait_for_modifiers", side_effect=lambda: self.set_rows([
            {**saved, "enabled": False},
        ])), patch.object(self.store, "runner") as runner:
            with self.assertRaisesRegex(shortcuts.ShortcutError, "disabled before typing"):
                self.store.type_text(saved["id"])
        runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
