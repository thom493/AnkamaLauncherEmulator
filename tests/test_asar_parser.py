import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from asar import AsarArchive

from ankama_launcher_emulator.utils.asar_parser import (
    extract_file_from_asar,
    read_file_from_asar,
)

ASAR_PATH = Path(__file__).resolve().parent.parent / "resources" / "app.asar"


class TestAsarParser(unittest.TestCase):
    """Verify the in-house ASAR parser against npm asar and the Python asar package."""

    @classmethod
    def setUpClass(cls) -> None:
        if not ASAR_PATH.exists():
            raise unittest.SkipTest(f"Test archive not found: {ASAR_PATH}")

    def test_extract_package_json_matches_npm_asar(self) -> None:
        """package.json bytes must match npm's `asar extract-file` output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # npm asar extract-file writes to cwd with original filename
            subprocess.run(
                ["asar", "extract-file", str(ASAR_PATH), "package.json"],
                check=True,
                capture_output=True,
                cwd=tmpdir,
            )
            npm_bytes = (Path(tmpdir) / "package.json").read_bytes()

        our_bytes = read_file_from_asar(ASAR_PATH, "package.json")

        self.assertEqual(
            len(npm_bytes),
            len(our_bytes),
            "Byte length mismatch with npm asar",
        )
        self.assertEqual(
            hashlib.sha256(npm_bytes).hexdigest(),
            hashlib.sha256(our_bytes).hexdigest(),
            "SHA-256 mismatch with npm asar",
        )

    def test_extract_package_json_matches_python_asar_package(self) -> None:
        """package.json bytes must match the `asar` PyPI package output."""
        with AsarArchive(ASAR_PATH, mode="r") as archive:
            expected = archive.read(Path("package.json"))

        actual = read_file_from_asar(ASAR_PATH, "package.json")

        self.assertEqual(expected, actual)

    def test_version_parsed_correctly(self) -> None:
        """The version field in package.json should be present and look like a Zaap version."""
        data = read_file_from_asar(ASAR_PATH, "package.json")
        pkg = json.loads(data.decode("utf-8"))
        version = pkg.get("version")

        self.assertIsNotNone(version)
        self.assertIsInstance(version, str)
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")

    def test_nested_file_matches_python_asar(self) -> None:
        """A deeply nested file must match the reference implementation."""
        nested = "media/common_loop--loop.mp4"

        with AsarArchive(ASAR_PATH, mode="r") as archive:
            expected = archive.read(Path(nested))

        actual = read_file_from_asar(ASAR_PATH, nested)

        self.assertEqual(expected, actual)
        self.assertEqual(
            hashlib.sha256(expected).hexdigest(),
            hashlib.sha256(actual).hexdigest(),
        )

    def test_binary_file_integrity(self) -> None:
        """Extracting a binary file should yield the exact same bytes."""
        binary_file = "0.bundle.js"

        with AsarArchive(ASAR_PATH, mode="r") as archive:
            expected = archive.read(Path(binary_file))

        actual = read_file_from_asar(ASAR_PATH, binary_file)

        self.assertEqual(expected, actual)

    def test_extract_file_to_disk(self) -> None:
        """extract_file_from_asar should write the correct data to disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "output" / "pkg.json"
            extract_file_from_asar(ASAR_PATH, "package.json", dest)

            self.assertTrue(dest.exists())
            self.assertEqual(
                dest.read_bytes(),
                read_file_from_asar(ASAR_PATH, "package.json"),
            )

    def test_missing_archive_raises(self) -> None:
        """A non-existent archive must raise FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            read_file_from_asar("/nonexistent/archive.asar", "package.json")

    def test_missing_internal_file_raises(self) -> None:
        """A missing internal path must raise FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            read_file_from_asar(ASAR_PATH, "definitely_not_here.txt")

    def test_directory_instead_of_file_raises(self) -> None:
        """Requesting a directory node must raise IsADirectoryError."""
        with self.assertRaises(IsADirectoryError):
            read_file_from_asar(ASAR_PATH, "media")


if __name__ == "__main__":
    unittest.main()
