"""Platform routing and inventory regression checks, without invoking Homebrew."""

import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sync_homebrew.py"
sys.path.insert(0, str(SCRIPT.parent))
import inventory_support as support
SPEC = importlib.util.spec_from_file_location("sync_homebrew", SCRIPT)
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


class SyncTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        root_patch = patch.object(sync, "ROOT", self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        self.source = {"machine": "machine-one", "prefix": "/brew", "architecture": "x86_64"}
        self.settings = {"tap:example/tap": 'tap "example/tap", trusted: true',
                         "brew:ripgrep": 'brew "ripgrep"', "cask:codex": 'cask "codex"'}
        self.metadata = {"formulae": [{"full_name": "ripgrep"}, {"full_name": "pcre2"}],
                         "casks": [{"full_token": "codex", "artifacts": []}]}

    def brew(self, *arguments):
        return {("--prefix",): ["/brew"], ("--cellar",): [str(self.root / "Cellar")],
                ("tap",): ["example/tap"]}[arguments]

    def run_sync(self, host, *options):
        output = io.StringIO()
        with (
            patch.object(sync.sys, "platform", host),
            patch.object(sync.sys, "argv", [str(SCRIPT), "--non-interactive", *options]),
            patch.object(sync, "brew", side_effect=self.brew),
            patch.object(sync, "bundle_settings", side_effect=lambda: dict(self.settings)),
            patch.object(sync, "installed_metadata", side_effect=lambda: self.metadata),
            patch.object(sync, "source_identity", side_effect=lambda prefix: dict(self.source)),
            contextlib.redirect_stdout(output),
        ):
            status = sync.main()
        return status, output.getvalue()

    def test_sync_routes_both_platforms_and_keeps_the_other_inventory(self):
        for host, selected, other in (("darwin", "Mac", "Linux"), ("linux", "Linux", "Mac")):
            with self.subTest(host=host):
                other_directory = self.root / other
                other_directory.mkdir(exist_ok=True)
                other_brewfile = other_directory / "Brewfile"
                other_dependencies = other_directory / "dependencies.txt"
                other_brewfile.write_text("# Other machine\n")
                other_dependencies.write_text("other-dependency\n")
                status, output = self.run_sync(host, "--adopt")
                self.assertEqual(status, 0)
                self.assertIn(f"Updated {selected}/Brewfile", output)
                generated = (self.root / selected / "Brewfile").read_text()
                self.assertIn('brew "ripgrep"', generated)
                self.assertIn('cask "codex"', generated)
                self.assertIn('tap "example/tap", trusted: true', generated)
                self.assertNotIn('brew "pcre2"', generated)
                self.assertIn("\npcre2\n", (self.root / selected / "dependencies.txt").read_text())
                self.assertEqual(other_brewfile.read_text(), "# Other machine\n")
                self.assertEqual(other_dependencies.read_text(), "other-dependency\n")
                self.assertEqual(self.run_sync(host, "--check")[0], 0)

    def test_check_reports_platform_paths_without_creating_files(self):
        for host, selected in (("darwin", "Mac"), ("linux", "Linux")):
            with self.subTest(host=host):
                status, output = self.run_sync(host, "--check")
                self.assertEqual(status, 1)
                self.assertIn(f"{selected}/Brewfile", output)
                self.assertIn(f"{selected}/dependencies.txt", output)
                self.assertFalse((self.root / selected).exists())

    def test_sync_preserves_custom_groups_and_entry_options(self):
        directory = self.root / "Linux"
        directory.mkdir()
        (directory / "Brewfile").write_text(
            '# -- Formulae: Search --\nbrew "ripgrep", restart_service: false\n'
        )
        self.assertEqual(self.run_sync("linux", "--adopt")[0], 0)
        generated = (directory / "Brewfile").read_text()
        self.assertIn('# -- Formulae: Search --\nbrew "ripgrep", restart_service: false', generated)

    def test_missing_entries_are_kept_or_pruned_in_the_selected_inventory(self):
        directory = self.root / "Linux"
        directory.mkdir()
        (directory / "Brewfile").write_text('tap "old/tap"\nbrew "missing"\n')
        self.assertEqual(self.run_sync("linux", "--adopt")[0], 0)
        self.assertIn('brew "missing"', (directory / "Brewfile").read_text())
        self.assertIn('tap "old/tap"', (directory / "Brewfile").read_text())
        self.assertEqual(self.run_sync("linux", "--prune")[0], 0)
        self.assertNotIn('brew "missing"', (directory / "Brewfile").read_text())
        self.assertNotIn('tap "old/tap"', (directory / "Brewfile").read_text())

    def test_unsupported_platform_fails_before_querying_homebrew(self):
        with (
            patch.object(sync.sys, "platform", "win32"),
            patch.object(sync.sys, "argv", [str(SCRIPT)]),
            patch.object(sync, "installed") as installed,
            contextlib.redirect_stderr(io.StringIO()) as errors,
            self.assertRaises(SystemExit) as result,
        ):
            sync.main()
        self.assertEqual(result.exception.code, 1)
        self.assertIn("Unsupported platform: win32", errors.getvalue())
        installed.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_existing_inventory_requires_explicit_adoption(self):
        directory = self.root / "Linux"
        directory.mkdir()
        path = directory / "Brewfile"
        path.write_text('brew "missing"\n')
        with contextlib.redirect_stderr(io.StringIO()) as errors, self.assertRaises(SystemExit):
            self.run_sync("linux")
        self.assertIn("unbound inventory", errors.getvalue())
        self.assertEqual(path.read_text(), 'brew "missing"\n')
        self.assertFalse((directory / support.STATE).exists())

    def test_other_machine_prefix_or_architecture_cannot_overwrite_inventory(self):
        self.run_sync("linux")
        directory = self.root / "Linux"
        original = {name: (directory / name).read_bytes() for name in support.FILES}
        for key, value in (("machine", "machine-two"), ("prefix", "/different-brew"), ("architecture", "arm64")):
            with self.subTest(key=key):
                old_value = self.source[key]
                self.source[key] = value
                for options in ((), ("--check",), ("--prune",)):
                    with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                        self.run_sync("linux", *options)
                    self.assertEqual(original, {name: (directory / name).read_bytes() for name in support.FILES})
                self.source[key] = old_value

    def test_profiles_isolate_different_machines(self):
        self.run_sync("linux")
        original = (self.root / "Linux" / "Brewfile").read_bytes()
        self.source["machine"] = "machine-two"
        self.run_sync("linux", "--profile", "server")
        self.assertTrue((self.root / "Linux" / "profiles" / "server" / "Brewfile").exists())
        self.assertEqual((self.root / "Linux" / "Brewfile").read_bytes(), original)
        self.assertEqual(self.run_sync("linux", "--profile", "server", "--check")[0], 0)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_sync("linux", "--profile", "../server")

    def test_adoption_rebinds_but_keeps_missing_entries(self):
        self.run_sync("linux")
        self.source["machine"] = "replacement-machine"
        self.settings.pop("brew:ripgrep")
        self.run_sync("linux", "--adopt")
        directory = self.root / "Linux"
        self.assertIn('brew "ripgrep"', (directory / "Brewfile").read_text())
        self.assertEqual(support.read_state(directory)["source"], self.source)

    def test_unsupported_content_is_rejected_without_touching_inventory(self):
        directory = self.root / "Linux"
        directory.mkdir()
        path = directory / "Brewfile"
        snippets = [
            'if OS.linux?\n  brew "ripgrep"\nend\n',
            'brew "ripgrep" if OS.linux?\n',
            'flatpak "org.mozilla.firefox"\n',
            'vscode "ms-python.python"\n',
            'ENV["VARIABLE"] = "value"\n',
            'brew "ripgrep",\n  link: false\n',
            'brew "ripgrep",\n',
            'brew "ripgrep", postinstall: system("echo hello")\n',
            'brew "ripgrep", args: ["HEAD"] if OS.linux?\n',
            'brew "ripgrep", postinstall: "#{system(\'echo hello\')}"\n',
            'brew "ripgrep"\nbrew "ripgrep", link: false\n',
        ]
        for snippet in snippets:
            with self.subTest(snippet=snippet):
                path.write_text(snippet)
                with contextlib.redirect_stderr(io.StringIO()) as errors, self.assertRaises(SystemExit):
                    self.run_sync("linux", "--adopt", "--prune")
                self.assertIn(str(path), errors.getvalue())
                self.assertEqual(path.read_text(), snippet)
                self.assertFalse((directory / support.STATE).exists())

    def test_comments_and_custom_content_survive_sync_and_pruning(self):
        directory = self.root / "Linux"
        directory.mkdir()
        custom = '# -- Custom content --\nif OS.linux?\n  flatpak "org.mozilla.firefox"\nend\n\n'
        (directory / "Brewfile").write_text(
            '# Search utilities\n# -- Formulae: Search --\nbrew "ripgrep" # Prefer this search tool\n'
            '# Remember this package\nbrew "missing"\n# Extra note\n' + custom
        )
        self.run_sync("linux", "--adopt", "--prune")
        generated = (directory / "Brewfile").read_text()
        for comment in ("# Search utilities", "# Remember this package", "# Extra note", "# Prefer this search tool"):
            self.assertIn(comment, generated)
        self.assertTrue(generated.endswith(custom))
        self.assertNotIn('brew "missing"', generated)
        self.assertEqual(self.run_sync("linux", "--check")[0], 0)

    def test_native_settings_are_captured_and_refreshed(self):
        self.settings["brew:ripgrep"] = 'brew "ripgrep", args: ["HEAD", "with-extra"], link: false, restart_service: :changed'
        self.settings["tap:example/tap"] = 'tap "example/tap", "https://example.com/custom.git", trusted: { formula: "tool", commands: ["command"] }'
        self.run_sync("linux")
        path = self.root / "Linux" / "Brewfile"
        self.assertIn(self.settings["brew:ripgrep"], path.read_text())
        self.assertIn(self.settings["tap:example/tap"], path.read_text())
        self.settings["brew:ripgrep"] = 'brew "ripgrep", link: true'
        self.settings["tap:example/tap"] = 'tap "example/tap", "https://example.com/custom.git"'
        self.run_sync("linux")
        generated = path.read_text()
        self.assertIn(self.settings["brew:ripgrep"], generated)
        self.assertNotIn("HEAD", generated)
        self.assertNotIn("restart_service", generated)
        self.assertNotIn("trusted:", generated)
        self.assertEqual(self.run_sync("linux", "--check")[0], 0)

    def test_manual_options_override_generated_settings(self):
        self.settings["brew:ripgrep"] = 'brew "ripgrep", link: false, restart_service: :changed'
        self.run_sync("linux")
        path = self.root / "Linux" / "Brewfile"
        path.write_text(path.read_text().replace(
            self.settings["brew:ripgrep"], 'brew "ripgrep", link: :overwrite, postinstall: "echo ready"'
        ))
        self.settings["brew:ripgrep"] = 'brew "ripgrep", args: ["HEAD"], restart_service: :changed'
        self.run_sync("linux")
        generated = path.read_text()
        self.assertIn('link: :overwrite', generated)
        self.assertIn('postinstall: "echo ready"', generated)
        self.assertIn('args: ["HEAD"]', generated)
        self.assertNotIn('restart_service:', generated)
        # Once a user removes an automatically generated option, it remains removed.
        self.assertEqual(self.run_sync("linux", "--check")[0], 0)

    def test_failed_snapshot_does_not_modify_existing_files(self):
        self.run_sync("linux")
        directory = self.root / "Linux"
        original = {name: (directory / name).read_bytes() for name in support.FILES}
        with patch.object(sync, "installed", side_effect=RuntimeError("snapshot failed")):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.run_sync("linux")
        self.assertEqual(original, {name: (directory / name).read_bytes() for name in support.FILES})

    def test_duplicate_cli_cask_policy_is_verified_and_saved(self):
        binary = self.root / "Cellar" / "goreleaser" / "1.0" / "bin" / "goreleaser"
        binary.parent.mkdir(parents=True)
        binary.write_text("formula binary")
        target = self.root / "bin" / "goreleaser"
        target.parent.mkdir()
        target.symlink_to(binary)
        self.settings["brew:goreleaser"] = 'brew "goreleaser"'
        self.settings["cask:vendor/tap/goreleaser"] = 'cask "vendor/tap/goreleaser"'
        self.metadata["formulae"].append({"full_name": "goreleaser"})
        cask = {"full_token": "vendor/tap/goreleaser",
                "artifacts": [{"binary": ["goreleaser"], "target": str(target)}]}
        self.metadata["casks"].append(cask)
        self.run_sync("linux")
        path = self.root / "Linux" / "Brewfile"
        self.assertNotIn('cask "vendor/tap/goreleaser"', path.read_text())
        self.assertIn('brew "goreleaser"', path.read_text())
        self.run_sync("linux", "--no-deduplicate-casks")
        self.assertIn('cask "vendor/tap/goreleaser"', path.read_text())
        self.assertEqual(self.run_sync("linux", "--check")[0], 0)
        # GUI content makes a cask nonredundant even when one binary overlaps.
        cask["artifacts"].append({"app": ["GoReleaser.app"]})
        self.run_sync("linux", "--deduplicate-casks")
        self.assertIn('cask "vendor/tap/goreleaser"', path.read_text())
        cask["artifacts"].pop()
        target.unlink()
        self.run_sync("linux")
        self.assertIn('cask "vendor/tap/goreleaser"', path.read_text())

    def test_new_unknown_packages_still_get_interactive_classification(self):
        previous = {"unknown": ("New installs", 'brew "unknown"')}
        with patch.object(sync, "ask_category", return_value=("Personal tools", False)) as ask:
            sync.assign_unknown("brew", {"unknown"}, previous, {}, new_names={"unknown"})
        ask.assert_called_once()
        self.assertEqual(previous["unknown"][0], "Personal tools")


class TransactionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.brewfile = self.directory / "Brewfile"
        self.dependencies = self.directory / "dependencies.txt"
        self.brewfile.write_text("original brewfile\n")
        self.dependencies.write_text("original dependencies\n")
        self.content = {self.brewfile: "new brewfile\n", self.dependencies: "new dependencies\n",
                        self.directory / support.STATE: "new state\n"}

    def test_replace_failure_rolls_back_every_file(self):
        original_replace = support.os.replace
        failed = False

        def fail_once(source, target):
            nonlocal failed
            if target == self.dependencies and not failed:
                failed = True
                raise OSError("disk error")
            return original_replace(source, target)

        with patch.object(support.os, "replace", side_effect=fail_once), self.assertRaises(OSError):
            support.commit_files(self.directory, self.content)
        self.assertEqual(self.brewfile.read_text(), "original brewfile\n")
        self.assertEqual(self.dependencies.read_text(), "original dependencies\n")
        self.assertFalse((self.directory / support.STATE).exists())
        self.assertFalse((self.directory / support.JOURNAL).exists())
        self.assertFalse((self.directory / support.STAGING).exists())

    def interrupt_commit(self):
        class SimulatedCrash(BaseException):
            pass

        original_replace = support.os.replace

        def crash(source, target):
            if target == self.dependencies:
                raise SimulatedCrash()
            return original_replace(source, target)

        with patch.object(support.os, "replace", side_effect=crash), self.assertRaises(SimulatedCrash):
            support.commit_files(self.directory, self.content)

    def test_crash_recovers_a_consistent_file_set_and_check_stays_read_only(self):
        # Create the same lock file used by the CLI before simulating a hard crash.
        (self.directory / ".sync.lock").touch()
        self.interrupt_commit()
        self.assertEqual(self.brewfile.read_text(), "new brewfile\n")
        self.assertEqual(self.dependencies.read_text(), "original dependencies\n")
        with self.assertRaisesRegex(RuntimeError, "interrupted sync"), support.inventory_lock(self.directory, check=True):
            pass
        self.assertTrue((self.directory / support.JOURNAL).exists())
        with contextlib.redirect_stdout(io.StringIO()), support.inventory_lock(self.directory):
            for path, content in self.content.items():
                self.assertEqual(path.read_text(), content)
        self.assertFalse((self.directory / support.JOURNAL).exists())
        self.assertFalse((self.directory / support.STAGING).exists())

    def test_corrupted_staging_is_detected_before_recovery_changes_files(self):
        self.interrupt_commit()
        (self.directory / support.STAGING / "new" / "dependencies.txt").write_text("damaged")
        before = {path: path.read_bytes() for path in (self.brewfile, self.dependencies)}
        with self.assertRaisesRegex(RuntimeError, "damaged staged file"):
            support.recover_transaction(self.directory)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertTrue((self.directory / support.JOURNAL).exists())

    def test_failed_rollback_is_retried_on_the_next_run(self):
        original_replace = support.os.replace

        def fail(source, target):
            if target == self.dependencies:
                raise OSError("disk still unavailable")
            return original_replace(source, target)

        with patch.object(support.os, "replace", side_effect=fail), self.assertRaises(OSError):
            support.commit_files(self.directory, self.content)
        self.assertTrue((self.directory / support.JOURNAL).exists())
        support.recover_transaction(self.directory)
        self.assertEqual(self.brewfile.read_text(), "original brewfile\n")
        self.assertEqual(self.dependencies.read_text(), "original dependencies\n")
        self.assertFalse((self.directory / support.STATE).exists())

    def test_staging_failure_never_touches_the_originals(self):
        original_write = support.atomic_write

        def fail(path, data):
            if path == self.directory / support.STAGING / "new" / "dependencies.txt":
                raise OSError("cannot stage dependencies")
            return original_write(path, data)

        with patch.object(support, "atomic_write", side_effect=fail), self.assertRaises(OSError):
            support.commit_files(self.directory, self.content)
        self.assertEqual(self.brewfile.read_text(), "original brewfile\n")
        self.assertEqual(self.dependencies.read_text(), "original dependencies\n")
        self.assertFalse((self.directory / support.STAGING).exists())

    def test_atomic_replacement_keeps_file_permissions(self):
        self.brewfile.chmod(0o600)
        support.commit_files(self.directory, self.content)
        self.assertEqual(self.brewfile.stat().st_mode & 0o777, 0o600)


class CaptureTests(unittest.TestCase):
    def test_dump_selects_only_homebrew_types_and_overrides_ambient_filters(self):
        from types import SimpleNamespace

        response = SimpleNamespace(returncode=0, stdout='brew "ripgrep", args: ["HEAD"], link: false\n', stderr="")
        with (
            patch.dict(sync.os.environ, {"HOMEBREW_BUNDLE_DUMP_NO_BREW": "1", "HOMEBREW_BUNDLE_NO_RESTART": "1"}),
            patch.object(sync.subprocess, "run", return_value=response) as command,
        ):
            result = sync.bundle_settings()
        self.assertIn("brew:ripgrep", result)
        self.assertEqual(command.call_args.args[0],
                         ["brew", "bundle", "dump", "--file=-", "--formula", "--cask", "--tap", "--no-describe"])
        environment = command.call_args.kwargs["env"]
        self.assertNotIn("HOMEBREW_BUNDLE_DUMP_NO_BREW", environment)
        self.assertNotIn("HOMEBREW_BUNDLE_NO_RESTART", environment)
        self.assertEqual(environment["HOMEBREW_NO_AUTO_UPDATE"], "1")

    def test_changed_installation_snapshot_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "changed during the snapshot"):
            sync.installed({"brew:missing": 'brew "missing"'}, {"formulae": [], "casks": []})

    def test_machine_identifiers_are_hashed(self):
        with patch.object(support, "machine_identity", return_value="private-machine-id"):
            source = support.source_identity("/brew")
        self.assertEqual(len(source["machine"]), 64)
        self.assertNotIn("private-machine-id", str(source))

    def test_macos_identity_uses_the_hardware_uuid(self):
        from types import SimpleNamespace

        response = SimpleNamespace(stdout='    "IOPlatformUUID" = "mac-hardware-uuid"\n')
        with patch.object(support.platform, "system", return_value="Darwin"), patch.object(support.subprocess, "run", return_value=response):
            self.assertEqual(support.machine_identity(), "mac-hardware-uuid")


if __name__ == "__main__":
    unittest.main()
