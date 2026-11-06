#!/usr/bin/env python3
"""Verify the exact reviewed source of explicitly maintained dependency forks."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib


def require(condition, message):
    if not condition:
        raise ValueError(message)


def git(root, *args):
    return subprocess.check_output(
        ["git", "-C", str(root), *args], stderr=subprocess.PIPE
    ).decode().strip()


def check(metadata, inventory, policy, lock):
    require(inventory.get("schema") == 1, "unknown owned-source schema")
    records = inventory.get("packages")
    require(isinstance(records, list) and records, "missing owned-source records")
    names = [record["name"] for record in records]
    require(len(set(names)) == len(names), "duplicate owned-source records")
    owned_policies = {
        name for name, entry in policy.get("policy", {}).items()
        if entry.get("audit-as-crates-io") is False
    }
    require(owned_policies == set(names), "owned-source policy and records differ")
    for package in metadata["packages"]:
        if (package.get("source") or "").startswith("git+"):
            require(package["name"] in names or policy.get("policy", {}).get(
                package["name"], {}).get("audit-as-crates-io") is True,
                f'{package["name"]}: Git source has no exact ownership or registry audit policy')
    for record in records:
        name = record["name"]
        require(record.get("owner") and record.get("review") and record.get("upstream_pr"),
                f"{name}: missing ownership or review provenance")
        packages = [p for p in metadata["packages"] if p["name"] == name]
        locked = [p for p in lock["package"] if p["name"] == name]
        require(len(packages) == len(locked) == 1, f"{name}: missing or duplicate package")
        package = packages[0]
        for description, entry in [("resolved", package), ("locked", locked[0])]:
            require(entry["version"] == record["version"], f"{name}: {description} version")
            require(entry.get("source") == record["source"], f"{name}: {description} source")
        require(record["source"].endswith(f'?rev={record["revision"]}#{record["revision"]}'),
                f"{name}: source is not pinned by immutable revision")
        manifest = Path(package["manifest_path"])
        require(not manifest.is_symlink(), f"{name}: symlink manifest")
        root = manifest.parent.resolve()
        require(manifest.name == "Cargo.toml", f"{name}: unexpected manifest")
        require(Path(git(root, "rev-parse", "--show-toplevel")).resolve() == root,
                f"{name}: package is not the reviewed repository root")
        require(git(root, "rev-parse", "HEAD") == record["revision"], f"{name}: wrong revision")
        require(git(root, "rev-parse", "HEAD^{tree}") == record["tree"], f"{name}: wrong tree")
        files = record["files"]
        require("Cargo.toml" in files and any(n.startswith("src/") for n in files),
                f"{name}: incomplete reviewed file inventory")
        tracked = set(git(root, "ls-files", "-z").split("\0")) - {""}
        require(tracked == set(files), f"{name}: tracked inventory changed")
        for relative, expected in files.items():
            path = Path(relative)
            require(not path.is_absolute() and ".." not in path.parts,
                    f"{name}: invalid reviewed path")
            actual = root / path
            require(actual.is_file() and not actual.is_symlink(), f"{name}: missing or linked {path}")
            require(actual.resolve().is_relative_to(root), f"{name}: escaping path {path}")
            require(hashlib.sha256(actual.read_bytes()).hexdigest() == expected["sha256"],
                    f"{name}: changed contents {path}")
            require(bool(actual.stat().st_mode & 0o111) == expected["executable"],
                    f"{name}: changed executable mode {path}")
        # Cargo writes these two files in dependency checkouts. Neither is used
        # as source; the workspace's locked graph is validated above. Every
        # other extra file is rejected, including ignored build.rs or .cargo
        # configuration files and files below an untracked source directory.
        permitted_generated = {".cargo-ok", "Cargo.lock"}
        for current, dirs, filenames in os.walk(root, followlinks=False):
            here = Path(current)
            dirs[:] = [d for d in dirs if not (here == root and d == ".git")]
            for directory in dirs:
                require(not (here / directory).is_symlink(), f"{name}: linked directory")
            for filename in filenames:
                candidate = here / filename
                relative = candidate.relative_to(root).as_posix()
                if relative == ".git":
                    continue
                require(not candidate.is_symlink(), f"{name}: linked file {relative}")
                require(relative in files or relative in permitted_generated,
                        f"{name}: unreviewed file {relative}")


def main():
    root = Path(__file__).resolve().parent.parent
    inventory = json.loads((root / "supply-chain/owned-sources.json").read_text())
    policy = tomllib.loads((root / "supply-chain/config.toml").read_text())
    lock = tomllib.loads((root / "Cargo.lock").read_text())
    metadata = json.loads(subprocess.check_output(
        ["cargo", "metadata", "--locked", "--all-features", "--format-version=1"], cwd=root
    ))
    check(metadata, inventory, policy, lock)
    print("Verified exact reviewed owned-source identities and contents")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(f"Owned-source verification failed: {error}")
