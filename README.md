# Homebrew inventories

Homebrew configurations for macOS and Linux, organized by purpose. Requires Python 3.12+ and [Homebrew](https://brew.sh/) on your `PATH`.

| Path | Contents |
| --- | --- |
| [Mac/](Mac/) | macOS Brewfile and dependency list |
| [Linux/](Linux/) | Linux Brewfile and dependency list |
| [scripts/sync_homebrew.py](scripts/sync_homebrew.py) | Syncs the current platform's inventory |

## Usage

Run from the repository root:

```sh
python3 scripts/sync_homebrew.py          # Sync installed packages
python3 scripts/sync_homebrew.py --check  # Check without writing
python3 scripts/sync_homebrew.py --help   # Show all options
```

Restore the matching inventory:

```sh
brew bundle install --file=Mac/Brewfile --no-upgrade
brew bundle install --file=Linux/Brewfile --no-upgrade
```

Each inventory is bound to a machine and Homebrew installation. Keep `.sync-state.json` in version control. On the owning Mac, bind the existing inventory once with `--adopt`. For another machine or installation, use `--profile NAME`.

Missing packages are kept by default; `--prune` removes them. Sync preserves categories, comments, and manual options, captures Homebrew installation settings, and supports recovery after interrupted writes. Unsupported syntax stops sync before files are overwritten.

See the [sync reference](docs/sync.md) for profiles, custom Ruby, cask deduplication, recovery, and restore limitations.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Inspired by [Lissy93/Brewfile](https://github.com/Lissy93/Brewfile). [MIT license](LICENSE).
