import unittest
from unittest.mock import patch

import native_install


class NativeInstallTests(unittest.TestCase):
    def test_requires_explicit_device_and_rejects_environment_injection(self):
        for value in (None, '', '/dev/dri/card0', '/dev/fb1\nUser=root', '/tmp/fb0'):
            with self.assertRaises(ValueError):
                native_install.validate_framebuffer(value, False)
        native_install.validate_framebuffer('/dev/fb1', False)

    def test_missing_driver_blocks_native_install(self):
        with patch('native_install.Path.is_char_device', return_value=False):
            with self.assertRaises(ValueError):
                native_install.check_dependencies('/dev/fb1')

    def test_display_has_hardware_permissions_and_owns_no_engine(self):
        unit = native_install.service_text('/dev/fb1')
        self.assertIn('QT_QPA_PLATFORM=linuxfb:fb=/dev/fb1', unit)
        self.assertIn('SupplementaryGroups=video input', unit)
        self.assertIn('DynamicUser=yes', unit)
        self.assertNotIn('User=root', unit)
        self.assertNotIn('backup.py', unit)
        self.assertNotIn('PartOf=', unit)
        self.assertNotIn('BindsTo=', unit)


if __name__ == '__main__':
    unittest.main()
