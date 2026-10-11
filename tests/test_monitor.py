import unittest
from unittest.mock import patch, Mock
from hardware import SystemMonitor, storage_usage


class MonitorTests(unittest.TestCase):
    def test_cpu_delta_and_available_memory(self):
        readings = iter(['cpu 10 0 10 80 0 0 0 0', 'MemTotal: 1000 kB\nMemAvailable: 400 kB', '10.4 0', '42000',
                         'cpu 40 0 30 130 0 0 0 0', 'MemTotal: 1000 kB\nMemAvailable: 400 kB', '11.4 0', '42000'])
        monitor = SystemMonitor()
        with patch('hardware.Path.read_text', side_effect=lambda: next(readings)):
            self.assertIsNone(monitor.sample()['cpu_percent'])
            result = monitor.sample()
        self.assertEqual(result['cpu_percent'], 50)
        self.assertEqual(result['memory']['used_bytes'], 600 * 1024)
        self.assertEqual(result['temperature_c'], 42)

    def test_read_only_probe_unmounts_even_when_statistics_fail(self):
        node = {'name': '/dev/sdz1', 'uuid': 'probe-test', 'fstype': 'ext4', 'mountpoints': []}
        with patch('hardware.os.geteuid', return_value=0, create=True), patch('hardware.os.statvfs', side_effect=OSError), patch('hardware.os.path.ismount', return_value=True), patch('hardware.subprocess.run', return_value=Mock()) as run:
            self.assertEqual(storage_usage(node, probe=True), (None, None))
        self.assertEqual(run.call_args_list[0].args[0][:3], ['mount', '-o', 'ro,noload'])
        self.assertEqual(run.call_args_list[1].args[0][:2], ['umount', '--'])
