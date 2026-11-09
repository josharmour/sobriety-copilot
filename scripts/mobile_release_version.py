#!/usr/bin/env python3
"""Plan mobile versions without touching the checkout or contacting stores."""
import argparse
import re


def parse_version(value):
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", value):
        raise ValueError("Version must be three nonnegative integers: x.y.z")
    return tuple(map(int, value.split(".")))


def plan(current, release="", version="", candidate=False, build_only=False,
         bump_build=True):
    try:
        marketing, build = current.split("+")
        parts = parse_version(marketing)
        if not re.fullmatch(r"[1-9][0-9]*", build):
            raise ValueError()
    except ValueError as exc:
        raise ValueError("Current version must be x.y.z+positive_build_number") from exc
    choices = bool(release) + bool(version) + bool(candidate)
    if choices > 1:
        raise ValueError("Choose only one of --release, --version, or --candidate")
    if not choices and not build_only:
        raise ValueError("Choose --release patch|minor|major for a NEW public version, "
                         "--candidate for an UNPUBLISHED release, or --build-only for a local beta")
    if release:
        if release not in ("patch", "minor", "major"):
            raise ValueError("--release must be patch, minor, or major")
        index = {"major": 0, "minor": 1, "patch": 2}[release]
        updated = list(parts)
        updated[index] += 1
        for following in range(index + 1, 3):
            updated[following] = 0
        marketing = ".".join(map(str, updated))
    if version:
        if parse_version(version) <= parts:
            raise ValueError("A new public version must exceed the current version; "
                             "use --candidate only to continue an unpublished release")
        marketing = version
    if (release or version) and not bump_build:
        raise ValueError("A new public version requires a new build number; remove --no-bump")
    return f"{marketing}+{int(build) + int(bump_build)}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", required=True)
    parser.add_argument("--release", default="")
    parser.add_argument("--version", default="")
    for flag, default in (("candidate", "false"), ("build-only", "false"), ("bump-build", "true")):
        parser.add_argument("--" + flag, choices=("true", "false"), default=default)
    args = parser.parse_args()
    try:
        print(plan(args.current, args.release, args.version, args.candidate == "true",
                   args.build_only == "true", args.bump_build == "true"))
    except ValueError as exc:
        parser.exit(2, f"Version error: {exc}\n")


if __name__ == "__main__":
    main()
