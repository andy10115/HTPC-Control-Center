from __future__ import annotations

import unittest
from unittest.mock import patch

from htpc_control_center.config import AppConfig
from htpc_control_center.tv.providers import PROVIDERS, TVProviderError, create_controller, provider_info


class ProviderRegistryTests(unittest.TestCase):
    def test_v1_registers_only_android(self) -> None:
        self.assertEqual([provider.key for provider in PROVIDERS], ["android"])
        self.assertEqual(provider_info("android").name, "Android TV / Google TV")

    def test_unknown_provider_fails_explicitly(self) -> None:
        config = AppConfig()
        config.tv.provider = "webos"
        with self.assertRaises(TVProviderError):
            create_controller(config)

    def test_android_factory_is_lazy(self) -> None:
        config = AppConfig()
        config.tv.provider = "android"
        config.tv.adb_path = "/fake/adb"
        with patch("htpc_control_center.tv.android.find_adb", return_value="/fake/adb"):
            controller = create_controller(config)
        self.assertEqual(controller.__class__.__name__, "ADBController")


if __name__ == "__main__":
    unittest.main()
