# My Mac, in a Brewfile

This repository tracks the Homebrew packages installed on my Mac. It is not a complete inventory of all software, but it is a record of what I explicitly requested from Homebrew. The `Brewfile` is the install list; `dependencies.txt` is an inventory of other formulae that Homebrew installed to satisfy dependencies.


## What is tracked

| File | Purpose |
| --- | --- |
| [`Brewfile`](Brewfile) | The packages to restore: formulae explicitly requested from Homebrew, installed casks, and taps. Sections group related tools; `##` subheadings collect multiple versions of a package inside its section. |
| [`dependencies.txt`](dependencies.txt) | Formulae installed locally that Homebrew does not mark as requested, with `##` headings for multiple versions. This is an inventory for review, not an install list. Homebrew resolves dependencies when you install the Brewfile. |
| [`scripts/sync.py`](scripts/sync.py) | Reconcile the files with what is currently installed. Requires Python 3.9+ and Homebrew. |

The division uses Homebrew's `installed_on_request` receipt field. Older or unusual receipts can be ambiguous, so review the generated lists before relying on them as a record of intent. Versions such as `postgresql@15` and `postgresql@18` are separate formulae; a Brewfile records these formula names, not exact patch versions.

## Update after installing software

```sh
python3 scripts/sync.py
```

New installs are added automatically. Familiar packages enter their usual section; otherwise they appear under **New installs**. Move a line into the section you prefer. The sync command preserves that placement and any options on the line on later runs. When two or more names in a section share a base package and at least one has a numeric `@version` suffix, sync collects them under a `##` subheading (for example, `postgresql@15` and `postgresql@18` under Databases). It retains Brewfile entries for packages that are temporarily absent from this Mac, which is useful when keeping a desired setup for another Mac.

To see whether the inventory needs updating without writing files:

```sh
python3 scripts/sync.py --check
```

To remove entries that are no longer installed here:

```sh
python3 scripts/sync.py --prune
```

Review the diff before committing. `--prune` edits repository files only; it does not uninstall software.

## Set up another Mac

Install [Homebrew](https://brew.sh/), clone this repository, review the Brewfile for apps and versioned formulae you want there, then run:

```sh
brew bundle install --file=Brewfile --no-upgrade
```

Homebrew may prompt for third-party tap trust, cask permissions, or a password. `brew bundle check --file=Brewfile --no-upgrade` checks for missing items. Avoid `brew bundle cleanup` unless you specifically want to remove software absent from this list.

Mac App Store apps and packages from other managers are outside this inventory. The `mas` formula itself is listed because it is installed through Homebrew.
