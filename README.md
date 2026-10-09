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

Sync uses package names and Homebrew descriptions to classify new packages. If it cannot identify a package, an interactive run lets you choose a formula or cask category. Non-interactive runs add unclear packages to **New installs**.

Sync also checks for packages that were removed. In an interactive run, you can decide what to do with them. In a non-interactive run, Sync removes their entries from the Brewfile.

Useful options:

- `--classify` — classify packages in **New installs**.
- `--keep-missing` — keep entries for packages missing from this Mac.
- `--non-interactive` — use the non-interactive defaults.

For all options, run `python3 scripts/sync.py --help`. Before restoring the Brewfile on another Mac, review its contents.

Inspired by [Lissy93/Brewfile](https://github.com/Lissy93/Brewfile). Licensed under [MIT](LICENSE).
