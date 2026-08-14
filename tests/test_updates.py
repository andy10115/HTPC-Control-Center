from __future__ import annotations

import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from htpc_control_center.paths import AppPaths
from htpc_control_center import updates


def make_paths(root: Path) -> AppPaths:
    config = root / "config"
    units = root / "systemd/user"
    return AppPaths(
        config_dir=config,
        data_dir=root / "data",
        state_dir=root / "state",
        runtime_dir=root / "runtime",
        config_file=config / "config.toml",
        user_unit_dir=units,
        user_unit_file=units / "htpc-control-center-tv-watcher.service",
    )


class UpdateTests(unittest.TestCase):
    def test_version_comparison(self) -> None:
        self.assertTrue(updates.is_newer_version("0.2.1", "0.2.0"))
        self.assertTrue(updates.is_newer_version("v1.0.0", "0.9.9"))
        self.assertFalse(updates.is_newer_version("0.2.0", "0.2.0"))
        self.assertFalse(updates.is_newer_version("0.1.9", "0.2.0"))
        with self.assertRaises(updates.UpdateError):
            updates.is_newer_version("nightly", "0.2.0")

    def test_preferences_default_on_and_can_disable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            self.assertTrue(updates.load_preferences(paths).automatically_check)
            updates.save_preferences(updates.UpdatePreferences(automatically_check=False), paths)
            self.assertFalse(updates.load_preferences(paths).automatically_check)
            self.assertFalse(updates.check_due(paths, now=100000.0))

    def test_forced_check_caches_new_stable_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            payload = {
                "tag_name": "v0.3.0",
                "html_url": "https://github.com/andy10115/HTPC-Control-Center/releases/tag/v0.3.0",
                "tarball_url": "https://api.github.com/repos/andy10115/HTPC-Control-Center/tarball/v0.3.0",
            }
            with patch.object(updates, "_request_latest_release", return_value=payload) as request:
                info = updates.check_for_updates(paths, force=True, now=1234.0)
            request.assert_called_once()
            self.assertIsNotNone(info)
            assert info is not None
            self.assertEqual(info.version, "0.3.0")
            self.assertEqual(updates.load_state(paths).last_check_epoch, 1234.0)
            self.assertEqual(updates.cached_available_update(paths), info)

    def test_automatic_check_uses_24_hour_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            state = updates.UpdateState(
                last_check_epoch=1000.0,
                latest_version="0.3.0",
                latest_tag="v0.3.0",
                latest_html_url="https://example.test/release",
                latest_tarball_url="https://example.test/release.tar.gz",
            )
            updates.save_state(state, paths)
            with patch.object(updates, "_request_latest_release") as request:
                info = updates.check_for_updates(paths, force=False, now=1000.0 + 60.0)
            request.assert_not_called()
            self.assertIsNotNone(info)

    def test_latest_same_version_returns_no_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            payload = {
                "tag_name": "v0.2.0",
                "html_url": "https://example.test/release",
                "tarball_url": "https://example.test/release.tar.gz",
            }
            with patch.object(updates, "_request_latest_release", return_value=payload):
                self.assertIsNone(updates.check_for_updates(paths, force=True, now=2000.0))

    def test_safe_extract_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "bad.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                member = tarfile.TarInfo("../escape")
                payload = b"bad"
                member.size = len(payload)
                tar.addfile(member, io.BytesIO(payload))
            with self.assertRaises(updates.UpdateError):
                updates._safe_extract(archive, root / "out")
            self.assertFalse((root / "escape").exists())

    def test_install_update_runs_release_installer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "release.tar.gz"
            source = root / "repo-v0.3.0"
            source.mkdir()
            installer = source / "install.sh"
            installer.write_text("#!/usr/bin/env bash\nset -e\necho update-ok\n", encoding="utf-8")
            with tarfile.open(archive, "w:gz") as tar:
                tar.add(source, arcname="HTPC-Control-Center-v0.3.0")

            info = updates.UpdateInfo(
                version="0.3.0",
                tag_name="v0.3.0",
                html_url="https://example.test/release",
                tarball_url="https://example.test/release.tar.gz",
            )

            def fake_download(_url: str, destination: Path, timeout: float = 30.0) -> None:
                destination.write_bytes(archive.read_bytes())

            with patch.object(updates, "_download", side_effect=fake_download):
                output = updates.install_update(info)
            self.assertIn("update-ok", output)

    def test_download_uses_github_json_media_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "download.tar.gz"

            class FakeResponse(io.BytesIO):
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    self.close()
                    return False

            captured = {}

            def fake_urlopen(request, timeout=30.0):
                captured["accept"] = request.get_header("Accept")
                captured["timeout"] = timeout
                return FakeResponse(b"archive-data")

            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                updates._download("https://api.github.com/example/tarball/v0.2.1", destination)

            self.assertEqual(captured["accept"], "application/vnd.github+json")
            self.assertEqual(destination.read_bytes(), b"archive-data")

    def test_bootstrap_uses_github_json_for_tarball_download(self) -> None:
        bootstrap = Path(__file__).resolve().parents[1] / "bootstrap.sh"
        text = bootstrap.read_text(encoding="utf-8")
        self.assertNotIn("application/octet-stream", text)
        self.assertGreaterEqual(text.count("application/vnd.github+json"), 2)


if __name__ == "__main__":
    unittest.main()
