# 🍺 Mac Brewfile

**macOS · Homebrew · Python 3.12+**

A compact record of my Mac's Homebrew setup, grouped by purpose with multiple versions of a tool kept together.

| File | What it contains |
| --- | --- |
| [Brewfile](Brewfile) | Requested formulae, casks, and taps to install on another Mac. |
| [dependencies.txt](dependencies.txt) | Formulae Homebrew installed as dependencies, kept for reference. |
| [sync.py](scripts/sync.py) | Updates both lists from this Mac's installed packages. |

## Quick start

Install [Homebrew](https://brew.sh/), then use these commands from the repository root:

```sh
python3 scripts/sync.py                          # Update after installing or removing software
python3 scripts/sync.py --check                  # Check for changes without writing files
brew bundle install --file=Brewfile --no-upgrade # Restore on another Mac
```

Sync classifies new packages by name and Homebrew description. If a package is unclear, an interactive terminal menu offers the appropriate formula or cask categories. Non-interactive runs put it in **New installs**. Sync also asks about removed packages in a terminal; non-interactive runs remove their entries from the Brewfile.

Use `--classify` to revisit **New installs**, `--keep-missing` to preserve packages absent from this Mac, or `--non-interactive` to use defaults. Run `python3 scripts/sync.py --help` for all options. Review the Brewfile before restoring it on a different Mac.

Inspired by [Lissy93/Brewfile](https://github.com/Lissy93/Brewfile). Licensed under [MIT](LICENSE).
