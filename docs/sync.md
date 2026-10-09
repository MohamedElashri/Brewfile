# Homebrew sync reference

Each platform has its own inventory. Its `Brewfile` contains requested formulae, installed casks, and taps; `dependencies.txt` records formulae installed as dependencies for reference. Multiple versions of a tool are grouped together.

Keep `.sync-state.json` in version control. It binds the inventory to a machine, Homebrew prefix, and architecture and records generated installation settings. The machine identifier is hashed. The script requires Python 3.12+.

## Quick start

Install [Homebrew](https://brew.sh/), then use these commands from the repository root:

```sh
python3 scripts/sync_homebrew.py         # Update after installing or removing software
python3 scripts/sync_homebrew.py --check # Check for changes without writing files
```

The script detects macOS or Linux and updates only `Mac/` or `Linux/`, respectively. It finds `brew` on your `PATH`. Follow Homebrew's setup instructions to add it to your shell, including on [Linux](https://docs.brew.sh/Homebrew-on-Linux). Homebrew must support `brew bundle dump --formula --cask --tap`; Linux casks require a Homebrew version that supports the selected casks.

The existing Mac inventory needs to be bound on its first sync. On the Mac that owns that inventory, run:

```sh
python3 scripts/sync_homebrew.py --adopt
```

Sync refuses to overwrite an inventory bound to another machine or installation. To intentionally transfer ownership, use `--adopt`. Missing entries are kept by default, including during adoption; use `--prune` explicitly to remove them.

Restore the matching inventory on another machine:

```sh
brew bundle install --file=Mac/Brewfile --no-upgrade   # On macOS
brew bundle install --file=Linux/Brewfile --no-upgrade # On Linux
```

The script can run from any working directory; the restore commands above assume the repository root. Review the selected Brewfile before restoring it.

Sync uses package names and Homebrew descriptions to classify new packages. If it cannot identify a package, an interactive run lets you choose a formula or cask category. Non-interactive runs add unclear packages to **New installs**.

Sync also checks for packages that were removed or are no longer marked as requested. Interactive runs let you choose whether to keep them, with **keep** as the default. Non-interactive runs keep them unless `--prune` is supplied. Retained formulae are excluded from the dependency reference list.

## Additional machines and installations

Use a named profile to keep another machine, an Intel/Apple Silicon installation, or a separate Homebrew prefix independent:

```sh
python3 scripts/sync_homebrew.py --profile server
python3 scripts/sync_homebrew.py --profile server --check
brew bundle install --file=Linux/profiles/server/Brewfile --no-upgrade
```

Profiles live in `Mac/profiles/NAME/` or `Linux/profiles/NAME/` and have the same source guard as the default inventories. A new profile binds automatically on its first successful sync. Restoring an inventory on another machine does not change its sync ownership.

## Installation settings and custom content

Sync uses Homebrew's own dump output to capture custom tap URLs, existing tap/package trust, build arguments, HEAD installs, linking choices, and started services. It only requests formulae, casks, and taps from Homebrew; it does not discover other package types. Captured settings refresh on subsequent syncs. Manually edited options take precedence, and custom categories and comments are preserved. This follows [Homebrew's Brewfile support](https://docs.brew.sh/Brew-Bundle-and-Brewfile).

The generated portion accepts simple, single-line `tap`, `brew`, and `cask` entries with literal arguments. Duplicate entries, conditional Ruby, multiline entries, and other package types cause sync to stop before overwriting any inventory files. Put arbitrary Ruby or manually managed package types at the end of the Brewfile after this marker:

```ruby
# -- Custom content --
if OS.linux?
  flatpak "org.mozilla.firefox"
end
```

Everything from the marker onward is preserved verbatim and is not classified, pruned, or synced. Keep packages in that block distinct from those managed above it to avoid duplicate declarations. They still participate when Homebrew evaluates the Brewfile during restore.

Sync omits a redundant CLI cask when a requested formula with the same name supplies all of its binaries and the cask has no additional application artifacts. This resolves the GoReleaser overlap in the Linux inventory. It does not uninstall anything. Use `--no-deduplicate-casks` to track both; that preference is saved per inventory. Use `--deduplicate-casks` to enable the policy again.

A Brewfile records installation choices, not exact versions or application data. Homebrew has no Brewfile lockfile; `--no-upgrade` skips upgrading existing packages but does not pin versions on a fresh installation. Pin state is not captured. Sync's `--check` checks inventory drift, not whether every package can be installed on another architecture or OS release. Use `brew bundle check --file=Linux/Brewfile --verbose` to check the selected inventory's dependencies on the current machine.

## Safe updates

Sync locks each inventory, stages all three files, and replaces each file atomically. A write error triggers rollback. A hard interruption leaves a durable, checksummed journal; the next normal sync recovers the complete file set before continuing. `--check` never writes or recovers files and reports when recovery is needed. Do not delete transaction files while recovery is pending. Readers outside this script do not take its lock, so run restore after sync finishes.

Run the regression tests without Homebrew or additional Python dependencies:

```sh
python3 -m unittest discover -s tests -v
```

Useful options:

- `--classify` — classify packages in **New installs**.
- `--keep-missing` — keep entries for packages missing from this machine.
- `--prune` — explicitly remove missing packages and taps.
- `--non-interactive` — use the non-interactive defaults.

For all options, run `python3 scripts/sync_homebrew.py --help`.

Inspired by [Lissy93/Brewfile](https://github.com/Lissy93/Brewfile). Licensed under [MIT](../LICENSE).
