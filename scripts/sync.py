#!/usr/bin/env python3
"""Refresh the personal Brewfile from this Mac's Homebrew installation."""

import argparse
import json
import os
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

def names(value):
    return set(value.split())


FORMULA_GROUPS = {
    "Databases": names("postgresql mysql-client sqlite berkeley-db@5 gdbm"),
    "Python": names("python pyenv pyenv-virtualenv pipx python-setuptools pyvim cffi cryptography pybind11"),
    "Languages and runtimes": names("asdf go node nvm pnpm yarn ruby rbenv ruby-build rust openjdk@17 lua luajit perl duktape"),
    "Shell and terminal": names("""
        atuin bash bat bottom btop ccat chezmoi colordiff coreutils circumflex
        duf dust emacs eza fd fzf helix hyperfine irssi jq lazygit ls-go micro
        nano neovim reattach-to-user-namespace rio-terminal ripgrep ripgrep-all
        starship stow tlrc tmux tree vim watch wget zellij zoxide asciinema
    """),
    "Developer tools": names("""
        act appstream autoconf binwalk cask cmake cppcheck ctags docker
        fswatch gcc gh git-delta git-lfs httpie hugo jsonlint llvm
        nasm pkgconf qemu sanad shellcheck tidy-html5 vint xcodes yamllint
        yj yq zola
    """),
    "System utilities": names("f3 free-mac mas parallel squashfs util-linux wimlib xz zstd"),
    "Media and documents": names("""
        agg ffmpeg ghostscript graphviz imagemagick img2pdf jbig2dec jbig2enc
        pandoc pngquant poppler proselint tesseract-lang typst unpaper write-good
    """),
    "Scientific computing": names("armadillo cfitsio eigen fftw gsl liblinear root xrootd"),
    "Graphics and UI": names("""
        cairo fontconfig freetype ftgl gd gdk-pixbuf gl2ps glew
        gobject-introspection graphene gsettings-desktop-schemas gtk+3 gtk4
        libadwaita qt vulkan-headers
    """),
    "Network and security": names("""
        aria2 c-ares davix dnscrypt-proxy gnupg gpgme infisical krb5 kstart
        libassuan libfido2 libgpg-error libidn libproxy nghttp2 nmap nss
        openssl pinentry-mac rclone rsync s3cmd wireguard-tools
    """),
    "AI tools": names("llmfit opencode"),
    "Libraries and frameworks": names("""
        aom aribb24 at-spi2-core boost cjson dav1d gettext icu4c jemalloc
        jpeg jpeg-turbo libarchive libcbor libev libffi libpng libpthread-stubs
        libtermkey libtiff libvterm little-cms2 lpeg luv lz4 msgpack
        nlohmann-json nspr openjpeg popt
    """),
}

CASK_GROUPS = {
    "Browsers": {"firefox@developer-edition", "helium-browser", "zen"},
    "Terminals and editors": {"codeedit", "contour", "ghostty", "hyper", "iterm2", "kitty", "oxide-terminal", "rio", "sinclair", "tabby", "vimr", "warp", "wezterm", "yaw", "zed"},
    "Developer apps": {"android-platform-tools", "bruno", "docker-desktop", "gitbutler", "gitkraken", "jetbrains-toolbox", "miniforge", "orbstack", "trae", "utm", "xpipe"},
    "AI tools": {"claude-code", "codex"},
    "Security and privacy": {"1password-cli", "adguard", "cryptomator", "keybase"},
    "Communication": {"discord", "mattermost", "proton-mail", "signal", "slack", "telegram"},
    "Documents and media": {"background-music", "capcut", "doughnut", "finetune", "mactex", "obsidian", "quarto", "skim", "texifier", "vlc"},
    "Mac utilities": {"aldente", "alt-tab", "applite", "bluesnooze", "deskpad", "displaylink", "dockdoor", "keka", "keycastr", "keyclu", "maccy", "openinterminal", "popclip", "raycast", "rectangle", "stats", "thaw", "updatest@beta", "vicinae", "xquartz"},
    "Cloud and sync": {"nextcloud", "seafile-client"},
}


def brew(*args):
    result = subprocess.run(["brew", *args], text=True, capture_output=True,
                            env={**os.environ, "HOMEBREW_NO_AUTO_UPDATE": "1"})
    if result.returncode:
        raise RuntimeError(f"brew {' '.join(args)} failed: {result.stderr.strip()}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def descriptions():
    """Use installed Homebrew metadata when an exact name rule does not cover a tool."""
    result = subprocess.run(["brew", "info", "--json=v2", "--installed"],
                            text=True, capture_output=True,
                            env={**os.environ, "HOMEBREW_NO_AUTO_UPDATE": "1"})
    if result.returncode:
        print("Warning: Homebrew descriptions unavailable; using package names.", file=sys.stderr)
        return {"brew": {}, "cask": {}}
    try:
        data = json.loads(result.stdout)
    except ValueError:
        print("Warning: Homebrew descriptions were invalid; using package names.", file=sys.stderr)
        return {"brew": {}, "cask": {}}
    return {
        "brew": {item["full_name"]: item.get("desc") or "" for item in data.get("formulae", [])},
        "cask": {item["full_token"]: item.get("desc") or "" for item in data.get("casks", [])},
    }


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
            if match:
                kind = match.group(1)
                group = current[1] if current and current[0] == kind else "New installs"
                groups[kind][match.group(3)] = (group, line)
    return taps, groups


def category(kind, name, previous, description="", reclassify=False):
    if not reclassify and name in previous and previous[name][0] not in {"Other tools", "New installs"}:
        return previous[name][0]
    family = version_family(name) or name
    for old_name in sorted(previous):
        if not reclassify and (version_family(old_name) or old_name) == family and previous[old_name][0] not in {"Other tools", "New installs"}:
            return previous[old_name][0]
    short = name.rsplit("/", 1)[-1]
    if kind == "cask" and short.startswith("font-"):
        return "Fonts"
    base = family.rsplit("/", 1)[-1]
    lookup = FORMULA_GROUPS if kind == "brew" else CASK_GROUPS
    for group, names in lookup.items():
        if short in names or base in names:
            return group
    description = description.lower()
    if kind == "brew":
        if short.endswith("-terminal") or "terminal emulator" in description:
            return "Shell and terminal"
        if short.startswith(("gtk", "qt")):
            return "Graphics and UI"
        if short.startswith("lib") or " library" in description:
            return "Libraries and frameworks"
        if any(term in description for term in ("github actions", "linter", "compiler", "build tool")):
            return "Developer tools"
    else:
        if "terminal emulator" in description or "gpu-accelerated terminal" in description:
            return "Terminals and editors"
        if "web browser" in description:
            return "Browsers"
        if any(term in description for term in ("password manager", "password management", "encryption tool")):
            return "Security and privacy"
        if any(term in description for term in ("code editor", "integrated development environment")):
            return "Developer apps"
    return previous[name][0] if name in previous else "New installs"


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


def category_choices(kind, previous):
    standard = list(FORMULA_GROUPS if kind == "brew" else CASK_GROUPS)
    if kind == "cask":
        standard.append("Fonts")
    custom = sorted({group for group, _ in previous.values()} - set(standard) - {"Other tools", "New installs"})
    return standard + custom


def ask_category(kind, name, description, choices, read=input):
    label = "formula" if kind == "brew" else "cask"
    print(f"\nNew {label}: {name}")
    if description:
        print("  " + re.sub(r"[\x00-\x1f\x7f]", " ", description))
    for number, group in enumerate(choices, 1):
        print(f"  {number:2}. {group}")
    print("   0. New installs (default)")
    print("   n. Create a category")
    print("   a. Put all remaining unknown packages in New installs")
    while True:
        try:
            answer = read("Category [0]: ").strip()
        except EOFError:
            return "New installs", True
        if answer in ("", "0"):
            return "New installs", False
        if answer.lower() == "a":
            return "New installs", True
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            return choices[int(answer) - 1], False
        if answer.lower() == "n":
            try:
                group = read("New category name: ").strip()
            except EOFError:
                return "New installs", True
            if group and len(group) <= 60 and group.isprintable() and "#" not in group and "--" not in group:
                return group, False
            print("Enter a printable category name of 1–60 characters, without # or --.")
            continue
        print("Choose a number, n, or a.")


def ask_missing(kind, name, read=input):
    label = "formula" if kind == "brew" else "cask"
    reason = "is no longer marked as requested" if kind == "brew" else "is no longer installed"
    print(f"\nPreviously tracked {label} {reason}: {name}")
    print("  0. Remove from Brewfile (default)")
    print("  1. Keep in Brewfile")
    plural = "formulae" if kind == "brew" else "casks"
    print(f"  a. Remove all remaining missing {plural}")
    print(f"  k. Keep all remaining missing {plural}")
    while True:
        try:
            answer = read("Choice [0]: ").strip().lower()
        except EOFError:
            return False, "remove"
        if answer in ("", "0"):
            return False, None
        if answer == "1":
            return True, None
        if answer == "a":
            return False, "remove"
        if answer == "k":
            return True, "keep"
        print("Choose 0, 1, a, or k.")


def review_missing(kind, installed_names, previous, interactive):
    missing = sorted(set(previous) - set(installed_names))
    if not interactive:
        return set()
    keep, mode = set(), None
    for name in missing:
        if mode is None:
            retain, mode = ask_missing(kind, name)
        else:
            retain = mode == "keep"
        if retain:
            keep.add(name)
    return keep


def assign_unknown(kind, installed_names, previous, metadata, revisit=False, skip_remaining=False):
    for name in sorted(installed_names):
        if name in previous and not (revisit and previous[name][0] in {"Other tools", "New installs"}):
            continue
        if category(kind, name, previous, metadata.get(name, "")) != "New installs":
            continue
        if skip_remaining:
            group = "New installs"
        else:
            choices = category_choices(kind, previous)
            group, skip_remaining = ask_category(kind, name, metadata.get(name, ""), choices)
        previous[name] = (group, previous.get(name, (None, f'{kind} "{name}"'))[1])
    return skip_remaining


def render(taps, formulae, casks, old_taps, old_groups, metadata, reclassify=False):
    lines = ["# Generated by python3 scripts/sync.py; move entries between sections to customize groups.",
             "# Requested formulae, installed casks, and any desired entries kept from previous syncs.", ""]
    if taps:
        lines += ["# -- Taps --"] + [old_taps.get(name, f'tap "{name}"') for name in sorted(taps)] + [""]
    for kind, names, title in (("brew", formulae, "Formulae"), ("cask", casks, "Casks")):
        grouped = {}
        for name in names:
            description = metadata[kind].get(name, "")
            group = category(kind, name, old_groups[kind], description, reclassify)
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
    missing_options = parser.add_mutually_exclusive_group()
    missing_options.add_argument("--prune", action="store_true", help="remove missing packages and taps without prompting")
    missing_options.add_argument("--keep-missing", action="store_true", help="keep packages absent from this Mac")
    parser.add_argument("--check", action="store_true", help="report whether generated files need updating")
    parser.add_argument("--classify", action="store_true", help="revisit existing New installs entries in the terminal menu")
    parser.add_argument("--non-interactive", action="store_true", help="use default choices without terminal menus")
    parser.add_argument("--reclassify", action="store_true", help="apply current category rules to existing entries")
    args = parser.parse_args()
    try:
        taps, formulae, casks, dependencies = installed()
    except (FileNotFoundError, RuntimeError) as error:
        parser.exit(1, f"Error: {error}\n")
    installed_formulae, installed_casks = set(formulae), set(casks)
    old_taps, groups = existing()
    interactive = not (args.check or args.non_interactive or args.prune) and sys.stdin.isatty() and sys.stdout.isatty()
    if args.keep_missing:
        formulae |= set(groups["brew"])
        casks |= set(groups["cask"])
    else:
        formulae |= review_missing("brew", formulae, groups["brew"], interactive)
        casks |= review_missing("cask", casks, groups["cask"], interactive)
    if not args.prune:
        taps |= set(old_taps)
    metadata = descriptions()
    if interactive:
        skip = assign_unknown("brew", installed_formulae, groups["brew"], metadata["brew"], args.classify)
        assign_unknown("cask", installed_casks, groups["cask"], metadata["cask"], args.classify, skip)
    dependencies -= formulae
    content = {
        BREWFILE: render(taps, formulae, casks, old_taps, groups, metadata, args.reclassify),
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
