#!/usr/bin/env python3
"""Refresh the personal Brewfile from this Mac's Homebrew installation."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BREWFILE = ROOT / "Brewfile"
DEPENDENCIES = ROOT / "dependencies.txt"
SECTION = re.compile(r"^# -- (Formulae|Casks): (.+) --$")
ENTRY = re.compile(r"^(brew|cask) ([\"'])(.+?)\2(?:,.*)?$")
TAP = re.compile(r"^tap ([\"'])(.+?)\1(?:,.*)?$")

FORMULA_GROUPS = {
    "Databases": {"postgresql", "mysql-client", "sqlite", "berkeley-db@5"},
    "Python": {"python", "pyenv", "pyenv-virtualenv", "pipx", "python-setuptools", "pyvim"},
    "Languages and runtimes": {"asdf", "go", "node", "nvm", "pnpm", "yarn", "ruby", "rbenv", "rust", "openjdk@17"},
    "Shell and terminal": {"atuin", "bash", "bat", "bottom", "btop", "ccat", "chezmoi", "colordiff", "coreutils", "duf", "dust", "emacs", "eza", "fd", "fzf", "helix", "hyperfine", "irssi", "jq", "lazygit", "micro", "nano", "neovim", "ripgrep", "ripgrep-all", "starship", "stow", "tlrc", "tmux", "tree", "vim", "watch", "wget", "zellij", "zoxide"},
    "Developer tools": {"act", "agg", "binwalk", "cmake", "cppcheck", "ctags", "docker", "gh", "git-delta", "git-lfs", "httpie", "hugo", "infisical", "jsonlint", "mas", "nasm", "opencode", "qemu", "root", "shellcheck", "typst", "xcodes", "yamllint", "yj", "yq", "zola"},
    "Media and documents": {"ffmpeg", "imagemagick", "img2pdf", "pandoc", "pngquant", "poppler", "tesseract-lang", "unpaper"},
    "Network and security": {"aria2", "dnscrypt-proxy", "gnupg", "nmap", "pinentry-mac", "rclone", "rsync", "s3cmd", "wireguard-tools"},
}

CASK_GROUPS = {
    "Browsers": {"firefox@developer-edition", "helium-browser", "zen"},
    "Terminals and editors": {"codeedit", "contour", "ghostty", "hyper", "iterm2", "kitty", "oxide-terminal", "rio", "tabby", "vimr", "warp", "wezterm", "zed"},
    "Developer apps": {"android-platform-tools", "bruno", "docker-desktop", "gitbutler", "gitkraken", "jetbrains-toolbox", "miniforge", "orbstack", "quarto", "trae", "utm", "xpipe"},
    "AI tools": {"claude-code", "codex"},
    "Communication": {"discord", "keybase", "mattermost", "proton-mail", "signal", "slack", "telegram"},
    "Documents and media": {"capcut", "doughnut", "finetune", "mactex", "obsidian", "texifier", "vlc"},
    "Mac utilities": {"adguard", "aldente", "alt-tab", "applite", "background-music", "bluesnooze", "cryptomator", "deskpad", "displaylink", "dockdoor", "keka", "keycastr", "keyclu", "maccy", "openinterminal", "popclip", "raycast", "rectangle", "skim", "stats", "thaw", "updatest@beta", "vicinae", "xquartz", "yaw"},
    "Cloud and sync": {"nextcloud", "seafile-client"},
}


def brew(*args):
    result = subprocess.run(["brew", *args], text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"brew {' '.join(args)} failed: {result.stderr.strip()}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def installed():
    formulae = set(brew("list", "--formula", "--full-name"))
    casks = set(brew("list", "--cask", "--full-name"))
    taps = set(brew("tap"))
    cellar = Path(brew("--cellar")[0])
    requested, dependencies = set(), set()
    for name in formulae:
        receipts = list((cellar / name.rsplit("/", 1)[-1]).glob("*/INSTALL_RECEIPT.json"))
        flags = []
        for receipt in receipts:
            try:
                flags.append(json.loads(receipt.read_text()).get("installed_on_request"))
            except (OSError, ValueError) as error:
                raise RuntimeError(f"Cannot read {receipt}: {error}") from error
        # An absent flag is ambiguous; retain that formula rather than losing it.
        (requested if not flags or any(flag is True or flag is None for flag in flags) else dependencies).add(name)
    return taps, requested, casks, dependencies


def existing():
    groups = {"brew": {}, "cask": {}}
    taps = {}
    if not BREWFILE.exists():
        return taps, groups
    current = None
    for line in BREWFILE.read_text().splitlines():
        match = SECTION.match(line)
        if match:
            current = ("brew" if match.group(1) == "Formulae" else "cask", match.group(2))
        elif match := TAP.match(line):
            taps[match.group(2)] = line
        else:
            match = ENTRY.match(line)
            if match and current and match.group(1) == current[0]:
                groups[match.group(1)][match.group(3)] = (current[1], line)
    return taps, groups


def category(kind, name, previous):
    if name in previous:
        return previous[name][0]
    family = version_family(name) or name
    for old_name in sorted(previous):
        if (version_family(old_name) or old_name) == family:
            return previous[old_name][0]
    short = name.rsplit("/", 1)[-1]
    if kind == "cask" and short.startswith("font-"):
        return "Fonts"
    base = family.rsplit("/", 1)[-1]
    lookup = FORMULA_GROUPS if kind == "brew" else CASK_GROUPS
    for group, names in lookup.items():
        if short in names or base in names:
            return group
    return "New installs" if previous else "Other tools"


def version_family(name):
    """Return a package's base name when its @ suffix starts with a version."""
    base, marker, suffix = name.rpartition("@")
    return base if marker and suffix[:1].isdigit() else None


def group_lines(kind, names, previous):
    by_family = {}
    for name in names:
        family = version_family(name) or name
        by_family.setdefault(family, []).append(name)
    multiples = {
        family: members for family, members in by_family.items()
        if len(members) > 1 and any(version_family(member) for member in members)
    }
    grouped_names = set().union(*(set(members) for members in multiples.values())) if multiples else set()
    def entry(name):
        default = name if kind == "dependency" else f'{kind} "{name}"'
        return previous.get(name, (None, default))[1]

    lines = [entry(name) for name in sorted(set(names) - grouped_names)]
    for family in sorted(multiples):
        lines.append(f'## {family.rsplit("/", 1)[-1]}')
        lines += [entry(name) for name in sorted(multiples[family])]
    return lines


def render(taps, formulae, casks, old_taps, old_groups):
    lines = ["# Generated by python3 scripts/sync.py; move entries between sections to customize groups.",
             "# Requested formulae, installed casks, and any desired entries kept from previous syncs.", ""]
    if taps:
        lines += ["# -- Taps --"] + [old_taps.get(name, f'tap "{name}"') for name in sorted(taps)] + [""]
    for kind, names, title in (("brew", formulae, "Formulae"), ("cask", casks, "Casks")):
        grouped = {}
        for name in names:
            group = category(kind, name, old_groups[kind])
            grouped.setdefault(group, []).append(name)
        preferred = list(FORMULA_GROUPS if kind == "brew" else CASK_GROUPS)
        if kind == "cask":
            preferred.append("Fonts")
        ordered = [name for name in preferred if name in grouped]
        ordered += sorted(set(grouped) - set(ordered) - {"New installs", "Other tools"})
        ordered += [name for name in ("Other tools", "New installs") if name in grouped]
        for group in ordered:
            lines.append(f"# -- {title}: {group} --")
            lines += group_lines(kind, grouped[group], old_groups[kind])
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prune", action="store_true", help="remove entries that are no longer installed")
    parser.add_argument("--check", action="store_true", help="report whether generated files need updating")
    args = parser.parse_args()
    try:
        taps, formulae, casks, dependencies = installed()
    except (FileNotFoundError, RuntimeError) as error:
        parser.exit(1, f"Error: {error}\n")
    old_taps, groups = existing()
    if not args.prune:
        taps |= set(old_taps)
        formulae |= set(groups["brew"])
        casks |= set(groups["cask"])
    dependencies -= formulae
    content = {
        BREWFILE: render(taps, formulae, casks, old_taps, groups),
        DEPENDENCIES: "# Installed formulae not marked as requested in Homebrew receipts. Generated by scripts/sync.py.\n"
                      + "\n".join(group_lines("dependency", dependencies, {})) + "\n",
    }
    changed = [path for path, data in content.items() if not path.exists() or path.read_text() != data]
    if args.check:
        print("Needs update: " + ", ".join(path.name for path in changed) if changed else "Brewfile inventory is current.")
        return 1 if changed else 0
    for path in changed:
        path.write_text(content[path])
        print(f"Updated {path.name}")
    print(f"{len(formulae)} formulae, {len(casks)} casks, {len(taps)} taps; {len(dependencies)} dependency formulae")
    return 0


if __name__ == "__main__":
    sys.exit(main())
