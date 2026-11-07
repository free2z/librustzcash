"""Exercise source identity failures against real isolated Git checkouts."""

import copy
import json
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest

from check_owned_sources import check


class OwnedSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parent.parent
        cls.inventory = json.loads((cls.root / "supply-chain/owned-sources.json").read_text())
        cls.policy = tomllib.loads((cls.root / "supply-chain/config.toml").read_text())
        cls.lock = tomllib.loads((cls.root / "Cargo.lock").read_text())
        cls.metadata = json.loads(subprocess.check_output(
            ["cargo", "metadata", "--locked", "--all-features", "--format-version=1"], cwd=cls.root
        ))

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="owned-source-test-")
        self.addCleanup(self.scratch.cleanup)
        self.inventory = copy.deepcopy(type(self).inventory)
        self.policy = copy.deepcopy(type(self).policy)
        self.lock = copy.deepcopy(type(self).lock)
        self.metadata = copy.deepcopy(type(self).metadata)
        self.package = next(p for p in self.metadata["packages"] if p["name"] == "utf8-zero")
        self.record = next(p for p in self.inventory["packages"] if p["name"] == "utf8-zero")
        self.checkout = Path(self.scratch.name) / "source"
        subprocess.run(["git", "clone", "--shared", "--no-checkout",
                        str(Path(self.package["manifest_path"]).parent), str(self.checkout)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "-C", str(self.checkout), "checkout", "--detach", self.record["revision"]],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.package["manifest_path"] = str(self.checkout / "Cargo.toml")

    def verify(self):
        check(self.metadata, self.inventory, self.policy, self.lock)

    def test_exact_source_passes(self):
        self.verify()

    def test_missing_inventory_fails(self):
        self.inventory["packages"] = []
        with self.assertRaises(ValueError): self.verify()

    def test_missing_manifest_fails(self):
        (self.checkout / "Cargo.toml").unlink()
        with self.assertRaises(ValueError): self.verify()

    def test_registry_duplicate_fails(self):
        extra = copy.deepcopy(self.package)
        extra["source"] = "registry+https://github.com/rust-lang/crates.io-index"
        self.metadata["packages"].append(extra)
        with self.assertRaises(ValueError): self.verify()

    def test_lock_and_resolved_source_must_both_match(self):
        for field in ["source", "version"]:
            with self.subTest(field=field):
                package = next(p for p in self.lock["package"] if p["name"] == "utf8-zero")
                before = package[field]
                package[field] = "different"
                with self.assertRaises(ValueError): self.verify()
                package[field] = before
                before = self.package[field]
                self.package[field] = "different"
                with self.assertRaises(ValueError): self.verify()
                self.package[field] = before

    def test_policy_cannot_expand_or_disappear(self):
        self.policy["policy"]["another-package"] = {"audit-as-crates-io": False}
        with self.assertRaises(ValueError): self.verify()
        del self.policy["policy"]["another-package"]
        del self.policy["policy"]["utf8-zero"]
        with self.assertRaises(ValueError): self.verify()

    def test_arbitrary_git_source_is_not_trusted(self):
        self.metadata["packages"].append({"name": "unreviewed", "source": "git+https://example.invalid/repo"})
        with self.assertRaises(ValueError): self.verify()

    def test_changed_source_fails(self):
        with (self.checkout / "src/read.rs").open("a") as file: file.write("\n// changed\n")
        with self.assertRaises(ValueError): self.verify()

    def test_extra_build_source_and_ignored_files_fail(self):
        for relative in ["build.rs", "src/extra.rs", "target/injected", ".cargo/config.toml"]:
            with self.subTest(path=relative):
                extra = self.checkout / relative
                extra.parent.mkdir(parents=True, exist_ok=True)
                extra.write_text("unreviewed")
                with self.assertRaises(ValueError): self.verify()
                extra.unlink()

    def test_symlink_fails(self):
        (self.checkout / "src/read.rs").unlink()
        (self.checkout / "src/read.rs").symlink_to(self.checkout / "src/lib.rs")
        with self.assertRaises(ValueError): self.verify()

    def test_extra_symlink_directory_fails(self):
        (self.checkout / "extra").symlink_to(self.checkout / "src", target_is_directory=True)
        with self.assertRaises(ValueError): self.verify()

    def test_executable_mode_fails(self):
        path = self.checkout / "src/read.rs"
        path.chmod(path.stat().st_mode | 0o111)
        with self.assertRaises(ValueError): self.verify()

    def test_reduced_inventory_fails(self):
        del self.record["files"]["src/read.rs"]
        with self.assertRaises(ValueError): self.verify()

    def test_git_identity_fails(self):
        self.record["tree"] = "0" * 40
        with self.assertRaises(ValueError): self.verify()


if __name__ == "__main__":
    unittest.main()
