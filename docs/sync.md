# My sync notes

I use `scripts/sync_homebrew.py` to keep my Homebrew records current after installing or removing packages. It requires Python 3.12+ and `brew` on my `PATH`.

Each platform has a `Brewfile` for requested formulae, casks, and taps, plus `dependencies.txt` for dependency formulae. I keep `.sync-state.json` in version control; it records generated settings and binds the inventory to my machine, Homebrew prefix, and architecture using a hashed machine identifier.

## Updating my inventories

From the repository root:

```sh
python3 scripts/sync_homebrew.py          # Update Mac/ or Linux/ automatically
python3 scripts/sync_homebrew.py --check  # Check without writing
python3 scripts/sync_homebrew.py --adopt  # Bind my existing Mac inventory once
```

I also use `--adopt` when intentionally moving an inventory to another machine or installation. Otherwise, a source mismatch blocks the sync.

Missing packages stay by default. These are the options I use to manage the lists:

| Option | Purpose |
| --- | --- |
| `--prune` | Remove missing packages and taps |
| `--keep-missing` | Keep missing packages without prompting |
| `--classify` | Revisit packages under **New installs** |
| `--reclassify` | Apply category rules to existing entries |
| `--non-interactive` | Skip menus and keep missing packages |

Unknown packages get a category menu in an interactive run or go under **New installs** otherwise. Formulae kept in the Brewfile are excluded from the dependency list. All options are listed by `--help`.

## Separate setups

I use profiles for another machine, architecture, or Homebrew installation:

```sh
python3 scripts/sync_homebrew.py --profile server
python3 scripts/sync_homebrew.py --profile server --check
brew bundle install --file=Linux/profiles/server/Brewfile --no-upgrade
```

Profiles live under `Mac/profiles/NAME/` or `Linux/profiles/NAME/` and bind on their first successful sync. Restoring a Brewfile elsewhere leaves its sync ownership unchanged. My default restore commands are in the [README](../README.md).

## Settings and manual entries

Sync captures tap URLs, existing trust, build arguments, HEAD installs, linking choices, and started services through [Homebrew's dump output](https://docs.brew.sh/Brew-Bundle-and-Brewfile). My edited options take precedence; categories and comments are preserved.

The managed portion accepts single-line `tap`, `brew`, and `cask` entries with literal arguments. Unsupported syntax or duplicate entries stops the sync before overwriting files. I put custom Ruby and other package types at the end:

```ruby
# -- Custom content --
if OS.linux?
  flatpak "org.mozilla.firefox"
end
```

That block is preserved verbatim and evaluated during restore. I keep its packages separate from the generated entries.

The Linux inventory keeps GoReleaser as a formula. Sync omits a matching CLI cask only when the requested formula supplies all its binaries and there are no additional application artifacts. The packages stay installed. `--no-deduplicate-casks` records both; `--deduplicate-casks` enables omission again. The preference is saved per inventory.

## Recovery and checks

Writes use a lock, atomic file replacements, and a recovery journal. Write errors trigger rollback; an interrupted sync recovers on the next normal run. I leave transaction files intact and finish syncing before restoring. `--check` reports pending recovery without changing files.

```sh
brew bundle check --file=Linux/Brewfile --verbose
python3 -m unittest discover -s tests -v
```

Sync's `--check` detects inventory changes; Homebrew's check verifies dependencies on the current machine. My Brewfiles record installation choices rather than exact versions or application data. Pin state is not captured, and `--no-upgrade` only skips upgrades to existing packages.
