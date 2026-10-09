# My Homebrew setup

I keep my Mac and Linux Homebrew packages here, grouped by purpose, so I can track changes and restore my setup.

- [Mac/](Mac/) — my Mac Brewfile and dependency list.
- [Linux/](Linux/) — my Linux Brewfile and dependency list.

## Sync and restore

My usual commands, from the repository root:

```sh
python3 scripts/sync_homebrew.py          # Update the current platform
python3 scripts/sync_homebrew.py --check  # Check for changes

brew bundle install --file=Mac/Brewfile --no-upgrade    # Restore my Mac setup
brew bundle install --file=Linux/Brewfile --no-upgrade  # Restore my Linux setup
```

I keep `.sync-state.json` with each inventory to guard against syncing from the wrong machine. My Mac needs `--adopt` on its first sync. I use `--profile NAME` for separate machines or installations and `--prune` to remove missing packages from the inventory.

Further details are in my [sync notes](docs/sync.md).
