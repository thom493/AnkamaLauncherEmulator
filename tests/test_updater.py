import os
import unittest
from unittest.mock import MagicMock, patch

from ankama_launcher_emulator.utils.updater import (
    GITHUB_API_LATEST,
    UpdateInfo,
    check_for_update,
    is_version_greater,
)


class TestIsVersionGreater(unittest.TestCase):
    def test_major_greater(self):
        self.assertTrue(is_version_greater("1.0.0", "0.9.9"))

    def test_minor_greater(self):
        self.assertTrue(is_version_greater("0.2.0", "0.1.9"))

    def test_patch_greater(self):
        self.assertTrue(is_version_greater("0.1.2", "0.1.1"))

    def test_same_version(self):
        self.assertFalse(is_version_greater("1.0.0", "1.0.0"))

    def test_older_version(self):
        self.assertFalse(is_version_greater("0.9.0", "1.0.0"))

    def test_strip_v_prefix(self):
        self.assertTrue(is_version_greater("v0.6.0", "0.5.0"))

    def test_double_digit_patch(self):
        self.assertTrue(is_version_greater("0.10.0", "0.9.0"))

    def test_different_length(self):
        self.assertTrue(is_version_greater("1.0", "0.9.9"))
        self.assertFalse(is_version_greater("0.9", "0.9.0"))


class TestCheckForUpdate(unittest.TestCase):
    @patch("ankama_launcher_emulator.utils.updater._current_version", return_value="0.5.0")
    @patch("ankama_launcher_emulator.utils.updater.requests.get")
    def test_update_available(self, mock_get, _mock_version):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "tag_name": "v0.6.0",
            "html_url": "https://github.com/owner/repo/releases/tag/v0.6.0",
            "assets": [{"browser_download_url": "https://example.com/dl.exe"}],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = check_for_update()
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["version"], "0.6.0")
        self.assertEqual(result["html_url"], "https://github.com/owner/repo/releases/tag/v0.6.0")
        self.assertEqual(result["download_url"], "https://example.com/dl.exe")
        mock_get.assert_called_once_with(GITHUB_API_LATEST, timeout=10)

    @patch("ankama_launcher_emulator.utils.updater._current_version", return_value="0.6.0")
    @patch("ankama_launcher_emulator.utils.updater.requests.get")
    def test_no_update_when_same_version(self, mock_get, _mock_version):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "tag_name": "v0.6.0",
            "html_url": "https://github.com/owner/repo/releases/tag/v0.6.0",
            "assets": [],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = check_for_update()
        self.assertIsNone(result)

    @patch("ankama_launcher_emulator.utils.updater._current_version", return_value="0.7.0")
    @patch("ankama_launcher_emulator.utils.updater.requests.get")
    def test_no_update_when_local_is_newer(self, mock_get, _mock_version):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "tag_name": "v0.6.0",
            "html_url": "https://github.com/owner/repo/releases/tag/v0.6.0",
            "assets": [],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = check_for_update()
        self.assertIsNone(result)

    @patch("ankama_launcher_emulator.utils.updater._current_version", return_value="0.5.0")
    @patch("ankama_launcher_emulator.utils.updater.requests.get")
    def test_network_failure_returns_none(self, mock_get, _mock_version):
        mock_get.side_effect = Exception("Connection timeout")

        result = check_for_update()
        self.assertIsNone(result)

    @patch("ankama_launcher_emulator.utils.updater._current_version", return_value="0.5.0")
    @patch("ankama_launcher_emulator.utils.updater.requests.get")
    def test_no_assets_returns_none_download_url(self, mock_get, _mock_version):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "tag_name": "v0.6.0",
            "html_url": "https://github.com/owner/repo/releases/tag/v0.6.0",
            "assets": [],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = check_for_update()
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIsNone(result["download_url"])


if __name__ == "__main__":
    unittest.main()
