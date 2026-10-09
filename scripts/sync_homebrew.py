#!/usr/bin/env python3
"""Refresh this platform's Homebrew inventory in Mac/ or Linux/."""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from inventory_support import (
    HEADER, SUMMARY, STATE, commit_files, inventory_lock, merge_entry,
    parse_entry, read_document, read_state, source_identity, validate_source,
)

ROOT = Path(__file__).resolve().parents[1]


def platform_directory():
    if sys.platform == "darwin":
        return ROOT / "Mac"
    if sys.platform.startswith("linux"):
        return ROOT / "Linux"
    raise RuntimeError(f"Unsupported platform: {sys.platform}; expected macOS or Linux.")


def names(value):
    return set(value.split())


FORMULA_GROUPS = {
    "Databases": names("postgresql mysql-client sqlite berkeley-db@5 gdbm"),
    "Python": names("python pyenv pyenv-virtualenv pipx python-setuptools pyvim cffi cryptography pybind11"),
    "Languages and runtimes": names("asdf go node nvm pnpm yarn ruby rbenv ruby-build rust openjdk@17 lua luajit perl duktape"),
    "Shell and terminal": names("""
        atuin bash bat bottom btop ccat chezmoi colordiff coreutils circumflex
        duf dust emacs eza fd fzf helix herdr hyperfine irssi jq lazygit ls-go micro
        nano neovim reattach-to-user-namespace rio-terminal ripgrep ripgrep-all
        snippy starship stow tlrc tmux tree vim watch wget zellij zoxide asciinema zmx
    """),
    "Developer tools": names("""
        act appstream autoconf binwalk cask cmake cppcheck ctags docker
        binutils fswatch gcc gh git-delta git-lfs golangci-lint goreleaser
        httpie hugo jsonlint lld llvm nasm nida pkgconf qemu sanad shellcheck
        tidy-html5 upx vint xcodes yamllint yj yq zig zola
    """),
    "System utilities": names("f3 free-mac lm-sensors mas parallel squashfs unzip util-linux wimlib xz zstd"),
    "Media and documents": names("""
        agg espeak-ng ffmpeg ghostscript graphviz imagemagick img2pdf jbig2dec jbig2enc
        pandoc pngquant poppler proselint tesseract-lang typst unpaper write-good
    """),
    "Scientific computing": names("armadillo arpack cfitsio eigen fftw gsl liblinear root xrootd"),
    "Graphics and UI": names("""
        cairo fontconfig freetype ftgl gd gdk-pixbuf gl2ps glew
        gobject-introspection graphene gsettings-desktop-schemas gtk+3 gtk4
        libadwaita qt vulkan-headers
    """),
    "Network and security": names("""
        aria2 awscli c-ares ca-certificates curl davix dnscrypt-proxy gnupg gpgme infisical krb5 kstart
        libassuan libfido2 libgpg-error libidn libproxy nghttp2 nmap nss
        openssl pinentry-mac rclone rsync s3cmd scorecard trivy wireguard-tools
    """),
    "AI tools": names("llama.cpp llmfit opencode pi-coding-agent"),
    "Libraries and frameworks": names("""
        abseil ada-url aom aribb24 assimp at-spi2-core boost brotli capstone
        cjson dav1d gettext icu4c jemalloc
        jpeg jpeg-turbo libarchive libcbor libev libffi libpng libpthread-stubs
        libtermkey libtiff libvterm little-cms2 lpeg luv lz4 msgpack
        nlohmann-json nspr openjpeg popt
    """),
}

CASK_GROUPS = {
    "Browsers": {"firefox@developer-edition", "helium-browser", "zen"},
    "Terminals and editors": {"codeedit", "contour", "ghostty", "hyper", "iterm2", "kitty", "oxide-terminal", "rio", "sinclair", "tabby", "vimr", "warp", "wezterm", "yaw", "zed"},
    "Developer apps": {"android-platform-tools", "bruno", "docker-desktop", "gitbutler", "gitkraken", "goreleaser", "jetbrains-toolbox", "miniforge", "orbstack", "trae", "utm", "xpipe"},
    "AI tools": {"claude-code", "codex"},
    "Security and privacy": {"1password-cli", "adguard", "cryptomator", "keybase"},
    "Communication": {"discord", "mattermost", "proton-mail", "signal", "slack", "telegram"},
    "Documents and media": {"background-music", "capcut", "doughnut", "finetune", "mactex", "obsidian", "quarto", "skim", "texifier", "vlc"},
    "Mac utilities": {"aldente", "alt-tab", "applite", "bluesnooze", "deskpad", "displaylink", "dockdoor", "keka", "keycastr", "keyclu", "maccy", "openinterminal", "popclip", "raycast", "rectangle", "stats", "thaw", "updatest@beta", "vicinae", "xquartz"},
    "Cloud and sync": {"nextcloud", "seafile-client"},
}


def brew_output(*args):
    # Ambient dump filters must not silently exclude packages or service settings.
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("HOMEBREW_BUNDLE_DUMP_NO_")
                   and key not in {"HOMEBREW_BUNDLE_NO_RESTART", "HOMEBREW_BUNDLE_NO_DESCRIBE"}}
    result = subprocess.run(["brew", *args], text=True, capture_output=True,
                            env={**environment, "HOMEBREW_NO_AUTO_UPDATE": "1"})
    if result.returncode:
        raise RuntimeError(f"brew {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def brew(*args):
    return [line.strip() for line in brew_output(*args).splitlines() if line.strip()]


def bundle_settings():
    """Let Homebrew capture trust, URLs, arguments, HEAD, linking, and services."""
    output = brew_output("bundle", "dump", "--file=-", "--formula", "--cask", "--tap", "--no-describe")
    settings = {}
    for line in output.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        try:
            entry = parse_entry(line)
        except ValueError as error:
            raise RuntimeError(f"Unsupported Homebrew dump entry: {line}: {error}") from error
        key = f"{entry.kind}:{entry.name}"
        if key in settings:
            raise RuntimeError(f"Duplicate Homebrew dump entry: {key}")
        settings[key] = line
    return settings


def installed_metadata():
    try:
        data = json.loads(brew_output("info", "--json=v2", "--installed"))
        if not isinstance(data.get("formulae"), list) or not isinstance(data.get("casks"), list):
            raise ValueError("missing installed package lists")
        for kind, key in (("formulae", "full_name"), ("casks", "full_token")):
            if any(not isinstance(item.get(key), str) for item in data[kind]):
                raise ValueError(f"invalid {kind} metadata")
        return data
    except (ValueError, AttributeError, TypeError) as error:
        raise RuntimeError(f"Invalid Homebrew installed metadata: {error}") from error


def descriptions(data):
    return {
        "brew": {item["full_name"]: item.get("desc") or "" for item in data["formulae"]},
        "cask": {item["full_token"]: item.get("desc") or "" for item in data["casks"]},
    }


def installed(settings, metadata):
    entries = [parse_entry(line) for line in settings.values()]
    requested = {entry.name for entry in entries if entry.kind == "brew"}
    casks = {entry.name for entry in entries if entry.kind == "cask"}
    formulae = {item["full_name"] for item in metadata["formulae"]}
    if not requested <= formulae or casks != {item["full_token"] for item in metadata["casks"]}:
        raise RuntimeError("Homebrew changed during the snapshot; rerun sync after package operations finish.")
    taps = set(brew("tap")) | {entry.name for entry in entries if entry.kind == "tap"}
    return taps, requested, casks, formulae - requested


def redundant_casks(formulae, metadata, prefix):
    """Omit CLI casks only when their binaries are supplied by a requested formula."""
    redundant = set()
    safe_artifacts = {"binary", "manpage", "bash_completion", "fish_completion", "zsh_completion",
                      "pwsh_completion", "generate_completions_from_executable", "zap"}
    cellar = Path(brew("--cellar")[0]).resolve()
    for item in metadata["casks"]:
        name = item["full_token"]
        owners = {formula.rsplit("/", 1)[-1] for formula in formulae
                  if formula.rsplit("/", 1)[-1] == name.rsplit("/", 1)[-1]}
        artifacts = item.get("artifacts", [])
        binaries = [artifact for artifact in artifacts if "binary" in artifact]
        if not owners or not binaries or any(set(artifact) - safe_artifacts - {"target"} for artifact in artifacts):
            continue
        for artifact in binaries:
            target = artifact.get("target")
            if not target:
                binary = artifact["binary"]
                if not binary or not isinstance(binary[0], str):
                    break
                target = str(Path(prefix) / "bin" / Path(binary[0]).name)
            target = Path(target)
            if not target.is_symlink():
                break
            try:
                owner = target.resolve(strict=True).relative_to(cellar).parts[0]
            except (OSError, ValueError, IndexError):
                break
            if owner not in owners:
                break
        else:
            redundant.add(name)
    return redundant


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


def group_lines(kind, names, previous, notes=None):
    notes = notes or {}
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

    lines = []
    for name in sorted(set(names) - grouped_names):
        lines += notes.get((kind, name), []) + [entry(name)]
    for family in sorted(multiples):
        lines.append(f'## {family.rsplit("/", 1)[-1]}')
        for name in sorted(multiples[family]):
            lines += notes.get((kind, name), []) + [entry(name)]
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
    print("  0. Keep in Brewfile (default)")
    print("  1. Remove from Brewfile")
    plural = "formulae" if kind == "brew" else "casks"
    print(f"  a. Remove all remaining missing {plural}")
    print(f"  k. Keep all remaining missing {plural}")
    while True:
        try:
            answer = read("Choice [0]: ").strip().lower()
        except EOFError:
            return True, "keep"
        if answer in ("", "0"):
            return True, None
        if answer == "1":
            return False, None
        if answer == "a":
            return False, "remove"
        if answer == "k":
            return True, "keep"
        print("Choose 0, 1, a, or k.")


def review_missing(kind, installed_names, previous, interactive):
    missing = sorted(set(previous) - set(installed_names))
    if not interactive:
        return set(missing)
    keep, mode = set(), None
    for name in missing:
        if mode is None:
            retain, mode = ask_missing(kind, name)
        else:
            retain = mode == "keep"
        if retain:
            keep.add(name)
    return keep


def assign_unknown(kind, installed_names, previous, metadata, revisit=False, skip_remaining=False, new_names=()):
    for name in sorted(installed_names):
        if name in previous and name not in new_names and not (revisit and previous[name][0] in {"Other tools", "New installs"}):
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


def render(taps, formulae, casks, old_taps, old_groups, metadata, reclassify=False, document=None):
    notes = document.notes if document else {}
    lines = [HEADER, SUMMARY, ""]
    kept = {("tap", name) for name in taps} | {("brew", name) for name in formulae} | {("cask", name) for name in casks}
    if taps:
        lines.append("# -- Taps --")
        for name in sorted(taps):
            lines += notes.get(("tap", name), []) + [old_taps.get(name, f'tap "{name}"')]
        lines.append("")
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
            lines += group_lines(kind, grouped[group], old_groups[kind], notes)
            lines.append("")
    if document:
        lines += document.trailing_notes
        for key in sorted(notes.keys() - kept):
            lines += notes[key]
        if document.custom:
            return "\n".join(lines).rstrip() + "\n\n" + document.custom
    return "\n".join(lines).rstrip() + "\n"


def sync_inventory(args, directory):
    brewfile = directory / "Brewfile"
    dependencies_file = directory / "dependencies.txt"
    document = read_document(brewfile)
    state = read_state(directory)
    prefix = brew("--prefix")[0]
    source = source_identity(prefix)
    validate_source(directory, state, source, args.adopt)
    settings = bundle_settings()
    raw_metadata = installed_metadata()
    taps, formulae, casks, dependencies = installed(settings, raw_metadata)
    old_taps, groups = document.taps, document.groups
    new_names = {kind: installed_names - set(groups[kind])
                 for kind, installed_names in (("brew", formulae), ("cask", casks))}
    prior_settings = state["settings"] if state else {}
    for key, line in settings.items():
        entry = parse_entry(line)
        if entry.kind == "tap":
            old_taps[entry.name] = merge_entry(old_taps.get(entry.name), line, prior_settings.get(key))
        else:
            previous = groups[entry.kind].get(entry.name)
            merged = merge_entry(previous[1] if previous else None, line, prior_settings.get(key))
            if previous:
                groups[entry.kind][entry.name] = (previous[0], merged)
            else:
                groups[entry.kind][entry.name] = ("New installs", merged)
    interactive = not (args.check or args.non_interactive or args.prune) and sys.stdin.isatty() and sys.stdout.isatty()
    installed_formulae, installed_casks = set(formulae), set(casks)
    if not args.prune:
        if args.keep_missing:
            formulae |= set(groups["brew"])
            casks |= set(groups["cask"])
        else:
            formulae |= review_missing("brew", formulae, groups["brew"], interactive)
            casks |= review_missing("cask", casks, groups["cask"], interactive)
        taps |= set(old_taps)
    deduplicate = args.deduplicate_casks
    if deduplicate is None:
        deduplicate = state.get("deduplicate_casks", True) if state else True
    duplicates = redundant_casks(installed_formulae, raw_metadata, prefix) if deduplicate else set()
    casks -= duplicates
    installed_casks -= duplicates
    if duplicates:
        print("Omitted redundant CLI casks supplied by formulae: " + ", ".join(sorted(duplicates)))
    metadata = descriptions(raw_metadata)
    if interactive:
        skip = assign_unknown("brew", installed_formulae, groups["brew"], metadata["brew"],
                              args.classify, new_names=new_names["brew"])
        assign_unknown("cask", installed_casks, groups["cask"], metadata["cask"],
                       args.classify, skip, new_names["cask"])
    dependencies -= formulae
    content = {
        brewfile: render(taps, formulae, casks, old_taps, groups, metadata, args.reclassify, document),
        dependencies_file: "# Installed formulae not marked as requested by Homebrew. Generated by scripts/sync_homebrew.py.\n"
                           + "\n".join(group_lines("dependency", dependencies, {})) + "\n",
        directory / STATE: json.dumps({"schema": 1, "source": source, "settings": settings,
                                       "deduplicate_casks": deduplicate}, indent=2, sort_keys=True) + "\n",
    }
    changed = [path for path, data in content.items() if not path.exists() or path.read_text() != data]
    if args.check:
        print("Needs update: " + ", ".join(str(path.relative_to(ROOT)) for path in changed)
              if changed else f"{directory.relative_to(ROOT)} Homebrew inventory is current.")
        return 1 if changed else 0
    if changed:
        # All inventory files and the source/settings state are one recoverable transaction.
        commit_files(directory, content)
        for path in changed:
            print(f"Updated {path.relative_to(ROOT)}")
    print(f"{len(formulae)} formulae, {len(casks)} casks, {len(taps)} taps; {len(dependencies)} dependency formulae")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    missing_options = parser.add_mutually_exclusive_group()
    missing_options.add_argument("--prune", action="store_true", help="explicitly remove missing packages and taps")
    missing_options.add_argument("--keep-missing", action="store_true", help="keep missing packages without prompting (non-interactive default)")
    parser.add_argument("--check", action="store_true", help="report changes without writing or recovering files")
    parser.add_argument("--classify", action="store_true", help="revisit existing New installs entries in the terminal menu")
    parser.add_argument("--non-interactive", action="store_true", help="use default choices without terminal menus")
    parser.add_argument("--reclassify", action="store_true", help="apply current category rules to existing entries")
    parser.add_argument("--profile", metavar="NAME", help="use Mac/profiles/NAME or Linux/profiles/NAME")
    parser.add_argument("--adopt", action="store_true", help="explicitly bind an existing inventory to this machine and Homebrew installation")
    parser.add_argument("--deduplicate-casks", action=argparse.BooleanOptionalAction, default=None,
                        help="omit redundant CLI casks whose binaries come from requested formulae (default: enabled; saved per inventory)")
    args = parser.parse_args()
    if args.profile and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", args.profile):
        parser.error("profile must be a name of 1–64 letters, digits, dots, underscores, or hyphens, starting with a letter or digit")
    try:
        directory = platform_directory()
        if args.profile:
            directory = directory / "profiles" / args.profile
        with inventory_lock(directory, args.check):
            return sync_inventory(args, directory)
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    sys.exit(main())
