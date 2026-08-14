from __future__ import annotations

import unittest

from htpc_control_center.config import AppConfig
from htpc_control_center.tv.android import (
    TVControlError,
    input_uri,
    parse_current_input,
    parse_power_state,
    parse_tv_inputs,
    set_tv_endpoint,
)


class AndroidBackendTests(unittest.TestCase):
    def test_power_state_parsing(self) -> None:
        self.assertTrue(parse_power_state("mWakefulness=Awake"))
        self.assertFalse(parse_power_state("mWakefulness=Asleep"))
        self.assertTrue(parse_power_state("state = ON"))
        self.assertIsNone(parse_power_state("nothing useful here"))

    def test_current_input_parsing(self) -> None:
        text = "header\n  inputId: com.vendor/.HdmiInputService/HW6\nfooter"
        self.assertEqual(parse_current_input(text), "com.vendor/.HdmiInputService/HW6")

    def test_physical_input_discovery_filters_tuners(self) -> None:
        text = """
TvInputInfo{id=com.vendor/.HdmiInputService/HW6, type=TYPE_HDMI, passthrough=true}
TvInputInfo{id=com.vendor/.HdmiInputService/HW3, type=TYPE_HDMI, passthrough=true}
TvInputInfo{id=com.android.tv/.TunerInputService/TUNER, type=TYPE_TUNER}
"""
        values = parse_tv_inputs(text)
        self.assertEqual([value.hardware_id for value in values], ["HW3", "HW6"])
        self.assertEqual(values[1].uri, input_uri(values[1].input_id))

    def test_endpoint_default_and_custom_port(self) -> None:
        config = AppConfig()
        set_tv_endpoint(config, "10.0.0.42")
        self.assertEqual(config.tv.serial, "10.0.0.42:5555")
        set_tv_endpoint(config, "10.0.0.42:37123")
        self.assertEqual(config.tv.serial, "10.0.0.42:37123")

    def test_endpoint_rejects_invalid_address(self) -> None:
        config = AppConfig()
        with self.assertRaises(TVControlError):
            set_tv_endpoint(config, "not-a-tv")
        with self.assertRaises(TVControlError):
            set_tv_endpoint(config, "2001:db8::1")


if __name__ == "__main__":
    unittest.main()
