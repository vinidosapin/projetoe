from __future__ import annotations

import shutil
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from projeto_e_video.release import (
    package_release,
    tree_digest,
    validate_baseline,
    validate_release,
    validate_zip,
)


PACKAGE = Path(__file__).resolve().parents[1]


class ReleaseTests(unittest.TestCase):
    def test_current_release_structure_is_valid(self) -> None:
        baseline_source = PACKAGE.parent / "Projeto_E_Cursos_em_Video_v1.0-alpha.5"
        report = validate_release(PACKAGE, require_origin=baseline_source.is_dir())
        self.assertTrue(report["valid"])
        if baseline_source.is_dir():
            self.assertTrue(report["baseline"]["verified"])
        else:
            self.assertFalse(report["baseline"]["available"])
        self.assertLess(report["total_file_bytes"], report["limit_bytes"])

    def test_tree_digest_is_stable(self) -> None:
        first = tree_digest(PACKAGE)
        second = tree_digest(PACKAGE)
        self.assertEqual(first, second)

    def test_package_has_exactly_one_root_and_valid_crc(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            copy = base / PACKAGE.name
            shutil.copytree(PACKAGE, copy)
            target = base / f"{PACKAGE.name}.zip"
            result = package_release(copy, target)
            self.assertTrue(result["zip"]["valid"])
            self.assertEqual(result["zip"]["root"], PACKAGE.name)
            self.assertTrue(validate_zip(target, PACKAGE.name)["valid"])

    def test_repackaging_unchanged_tree_is_byte_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            copy = base / PACKAGE.name
            shutil.copytree(PACKAGE, copy)
            target = base / f"{PACKAGE.name}.zip"
            first = package_release(copy, target)["zip"]["sha256"]
            second = package_release(copy, target, overwrite=True)["zip"]["sha256"]
            self.assertEqual(first, second)

    def test_secret_named_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            copy = base / PACKAGE.name
            shutil.copytree(PACKAGE, copy)
            (copy / ".env").write_text("SAMPLE=true", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "release inválida"):
                validate_release(copy)

    def test_build_install_and_media_artifacts_are_rejected(self) -> None:
        cases = (
            Path("build") / "artifact.txt",
            Path("package.egg-info") / "PKG-INFO",
            Path("sample.wav"),
        )
        for relative in cases:
            with self.subTest(path=relative.as_posix()), tempfile.TemporaryDirectory() as name:
                base = Path(name)
                copy = base / PACKAGE.name
                shutil.copytree(PACKAGE, copy)
                target = copy / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"not distributable")
                with self.assertRaisesRegex(ValueError, "release inválida"):
                    validate_release(copy)

    def test_zip_with_two_roots_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            archive = Path(name) / "bad.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("one/a.txt", "a")
                handle.writestr("two/b.txt", "b")
            with self.assertRaisesRegex(ValueError, "uma raiz"):
                validate_zip(archive, "one")

    def test_zip_symlink_is_rejected_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            copy = base / PACKAGE.name
            shutil.copytree(PACKAGE, copy)
            archive = base / f"{PACKAGE.name}.zip"
            package_release(copy, archive)
            link = zipfile.ZipInfo(f"{PACKAGE.name}/docs/link")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(archive, "a") as handle:
                handle.writestr(link, "../../fora")
            with self.assertRaisesRegex(ValueError, "simbólico"):
                validate_zip(archive, PACKAGE.name)

    def test_zip_install_metadata_is_rejected_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            archive = Path(name) / "bad.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr(
                    f"{PACKAGE.name}/package.egg-info/PKG-INFO",
                    "not distributable",
                )
            with self.assertRaisesRegex(ValueError, "metadata de instalação"):
                validate_zip(archive, PACKAGE.name)

    def test_version_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            copy = base / PACKAGE.name
            shutil.copytree(PACKAGE, copy)
            pyproject = (copy / "pyproject.toml").read_text(encoding="utf-8")
            (copy / "pyproject.toml").write_text(
            pyproject.replace('version = "1.0.0a6"', 'version = "9.9.0"'),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "pyproject"):
                validate_release(copy, require_current_manifest=False)

    def test_baseline_hash_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            copy = base / PACKAGE.name
            baseline_source = PACKAGE.parent / "Projeto_E_Cursos_em_Video_v1.0-alpha.5"
            if not baseline_source.is_dir():
                self.skipTest("baseline alpha.5 histórica não é distribuída neste bundle")
            baseline_copy = base / baseline_source.name
            shutil.copytree(PACKAGE, copy)
            shutil.copytree(baseline_source, baseline_copy)
            marker = baseline_copy / "VERSION"
            marker.write_text(marker.read_text(encoding="utf-8") + " ", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "baseline diverge"):
                validate_baseline(copy, require_available=True)


if __name__ == "__main__":
    unittest.main()
