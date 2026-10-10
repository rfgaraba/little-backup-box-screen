import unittest
from unittest.mock import patch

import native_install


class NativeInstallTests(unittest.TestCase):
    def test_installs_missing_qt_and_checks_again(self):
        with patch('native_install.validate_framebuffer'), patch('native_install.qt_available', side_effect=[False, True]) as probe, patch('native_install.install_packages') as apt:
            native_install.check_dependencies('/dev/fb1', install_missing=True)
            apt.assert_called_once_with(['python3-pyqt6'])
            self.assertEqual(probe.call_count, 2)

    def test_existing_qt_needs_no_package_changes(self):
        with patch('native_install.validate_framebuffer'), patch('native_install.qt_available', return_value=True), patch('native_install.install_packages') as apt:
            native_install.check_dependencies('/dev/fb1', install_missing=True)
            apt.assert_not_called()

    def test_missing_linuxfb_after_install_is_reported(self):
        with patch('native_install.validate_framebuffer'), patch('native_install.qt_available', return_value=False), patch('native_install.install_packages'):
            with self.assertRaisesRegex(ValueError, 'plugin LinuxFB'):
                native_install.check_dependencies('/dev/fb1', install_missing=True)

    def test_apt_updates_and_installs_only_requested_packages(self):
        with patch('native_install.shutil.which', return_value='/usr/bin/apt-get'), patch('native_install.subprocess.run') as run:
            native_install.install_packages(['python3-pyqt6'])
            self.assertEqual(run.call_args_list, [
                unittest.mock.call(['/usr/bin/apt-get', 'update'], check=True),
                unittest.mock.call(['/usr/bin/apt-get', 'install', '-y', 'python3-pyqt6'], check=True)])

    def test_apt_failure_stops_installation(self):
        import subprocess
        with patch('native_install.shutil.which', return_value='/usr/bin/apt-get'), patch('native_install.subprocess.run', side_effect=subprocess.CalledProcessError(1, 'apt-get')) as run:
            with self.assertRaisesRegex(ValueError, 'No se pudieron instalar'):
                native_install.install_packages(['python3-pyqt6'])
            self.assertEqual(run.call_count, 1)

    def test_display_connects_to_selected_port(self):
        self.assertIn('native.py --port 8081', native_install.service_text('/dev/fb1', 8081))
        with self.assertRaises(ValueError):
            native_install.service_text('/dev/fb1', 65536)

    def test_requires_explicit_device_and_rejects_environment_injection(self):
        for value in (None, '', '/dev/dri/card0', '/dev/fb1\nUser=root', '/tmp/fb0'):
            with self.assertRaises(ValueError):
                native_install.validate_framebuffer(value, False)
        native_install.validate_framebuffer('/dev/fb1', False)

    def test_missing_driver_blocks_native_install(self):
        with patch('native_install.Path.is_char_device', return_value=False), patch('native_install.install_packages') as apt:
            with self.assertRaises(ValueError):
                native_install.check_dependencies('/dev/fb1', install_missing=True)
            apt.assert_not_called()

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
