import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bluetooth import Bluetooth, ADAPTER, DEVICE
from remote_backup import RemoteBackup
from server import Engine


class BluetoothTests(unittest.TestCase):
    def setUp(self):
        self.bt = Bluetooth()
        self.adapter = '/org/bluez/hci0'
        self.device = self.adapter + '/dev_12_34_56_78_90_AB'
        self.objects = {self.adapter: {ADAPTER: {'Powered': True}}, self.device: {DEVICE: {
            'Adapter': self.adapter, 'Address': '12:34:56:78:90:AB', 'Alias': 'Teclado', 'Paired': False, 'Connected': False}}}
        self.bt._objects = Mock(return_value=self.objects)
        self.interface = Mock()
        self.bt._interface = Mock(return_value=self.interface)
        self.bt.dbus = Mock(Boolean=bool, UInt32=int)
        self.bt.glib = Mock()

    def test_status_distinguishes_power_connection_and_pairing(self):
        self.assertTrue(self.bt.status()['powered'])
        self.assertFalse(self.bt.status()['connected'])
        self.objects[self.device][DEVICE]['Connected'] = True
        self.assertTrue(self.bt.status()['connected'])
        self.objects[self.adapter][ADAPTER]['Powered'] = False
        self.assertFalse(self.bt.status()['powered'])

    def test_demo_does_not_touch_bus(self):
        bt = Bluetooth(enabled=False)
        self.assertFalse(bt.status()['available'])
        with self.assertRaises(ValueError):
            bt.apply({'action': 'power', 'enabled': True})
        self.assertIsNone(bt.bus)

    def test_pair_is_async_and_does_not_trust_before_success(self):
        self.bt._agent = Mock()
        self.bt.apply({'action': 'pair', 'device': self.device})
        self.assertEqual(self.bt.pairing, self.device)
        self.interface.Set.assert_not_called()
        with self.assertRaises(ValueError):
            self.bt.apply({'action': 'pair', 'device': self.device})
        self.interface.Pair.call_args.kwargs['reply_handler']()
        self.assertIsNone(self.bt.pairing)
        self.interface.Set.assert_called_once_with(DEVICE, 'Trusted', True)

    def test_pair_failure_reports_error_without_trusting(self):
        self.bt._paired(self.device, error='authentication failed')
        self.assertIn('No se pudo', self.bt.message)
        self.interface.Set.assert_not_called()

    def test_remove_and_connect_validate_device_paths(self):
        self.bt._agent = Mock()
        for action, method in [('connect', 'Connect'), ('disconnect', 'Disconnect'), ('remove', 'RemoveDevice')]:
            self.bt.apply({'action': action, 'device': self.device})
            getattr(self.interface, method).assert_called_once()
        with self.assertRaises(ValueError):
            self.bt.apply({'action': 'remove', 'device': '/org/bluez/hci1/dev_other'})

    def test_connection_can_request_authorization_without_blocking_http(self):
        self.bt._agent = Mock()
        self.bt.apply({'action': 'connect', 'device': self.device})
        self.assertEqual(self.bt.connecting, self.device)
        with self.assertRaises(ValueError):
            self.bt.apply({'action': 'connect', 'device': self.device})
        reply, error = Mock(), Mock()
        self.bt._ask(self.device, 'authorize', reply, error)
        self.bt.apply({'action': 'respond', 'prompt': self.bt.prompt['id'], 'accept': True})
        self.bt.glib.idle_add.call_args.args[0]()
        reply.assert_called_once_with()
        self.interface.Connect.call_args.kwargs['reply_handler']()
        self.assertIsNone(self.bt.connecting)

    def test_pin_is_validated_and_stale_prompts_rejected(self):
        reply, error = Mock(), Mock()
        self.bt._ask(self.device, 'passkey', reply, error)
        identifier = self.bt.prompt['id']
        with self.assertRaises(ValueError):
            self.bt.apply({'action': 'respond', 'prompt': identifier, 'accept': True, 'value': '1000000'})
        self.bt.apply({'action': 'respond', 'prompt': identifier, 'accept': True, 'value': '000123'})
        self.bt.glib.idle_add.call_args.args[0]()
        reply.assert_called_once_with(123)
        self.assertIsNone(self.bt.prompt)
        with self.assertRaises(ValueError):
            self.bt.apply({'action': 'respond', 'prompt': identifier, 'accept': True})

    def test_discovery_is_bounded_and_not_started_twice(self):
        with patch('bluetooth.threading.Timer') as timer:
            self.bt.apply({'action': 'scan'})
            self.bt.apply({'action': 'scan'})
            self.interface.StartDiscovery.assert_called_once()
            self.assertEqual(timer.call_args.args[0], 20)
            self.bt._stop_scan(self.adapter)
            self.interface.StopDiscovery.assert_called_once()


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'rclone.conf'
        self.path.write_text('[drive]\ntype = drive\ntoken = SECRET\n', encoding='utf-8')
        patcher = patch('remote_backup.state_dir', return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.remote = RemoteBackup({'engine_dir': '/engine'})
        self.remote.config_path = Mock(return_value=self.path)

    def test_catalog_contains_names_and_types_without_secrets(self):
        status = self.remote.status()
        self.assertEqual(status['targets'], [{'id': 'cloud:drive', 'label': 'drive', 'type': 'drive'}])
        self.assertNotIn('SECRET', str(status))

    def test_selection_persists_and_generates_upstream_command_for_exact_disk(self):
        self.remote.save({'enabled': True, 'target': 'cloud:drive'})
        self.assertEqual(RemoteBackup({'engine_dir': '/engine'}).settings, self.remote.settings)
        argv = self.remote.command({'engine': 'usb', 'id': 'ssd', 'preset': '--uuid exact'}, True)
        self.assertIn('cloud:drive', argv)
        self.assertIn('--uuid exact', argv)
        self.assertEqual(argv[argv.index('--move-files') + 1], 'False')
        self.assertEqual(argv[argv.index('--power-off') + 1], 'False')

    def test_unknown_target_cannot_be_enabled(self):
        with self.assertRaises(ValueError):
            self.remote.save({'enabled': True, 'target': 'cloud:unknown'})
        self.assertFalse(self.remote.settings['enabled'])

    def test_import_merges_and_refuses_to_replace_existing_accounts(self):
        # Ownership is tested on Linux using the installed www-data account.
        self.remote.import_config('[sftp]\ntype = sftp\nhost = example.org\n')
        self.assertEqual(len(self.remote.status()['targets']), 2)
        self.assertIn('SECRET', self.path.read_text())
        with self.assertRaises(ValueError):
            self.remote.import_config('[drive]\ntype = drive\ntoken = REPLACEMENT\n')
        self.assertNotIn('REPLACEMENT', self.path.read_text())
        self.assertFalse(self.path.with_name('rclone.conf.screen.tmp').exists())

    def test_invalid_import_does_not_modify_configuration(self):
        before = self.path.read_bytes()
        for text in ['not a config', '[bad:name]\ntype = drive', '[no-type]\ntoken = secret', 'RCLONE_ENCRYPT_V0:xxx']:
            with self.assertRaises(ValueError):
                self.remote.import_config(text)
        self.assertEqual(before, self.path.read_bytes())

    def test_remote_runs_only_after_confirmed_local_success(self):
        for local in ['success', 'review', 'error', 'cancelled']:
            with self.subTest(local=local):
                engine = Engine()
                with patch.object(engine, '_run_phase', side_effect=[{'state': local}, {'state': 'success'}]) as run:
                    engine.run(['local'], ['remote'])
                self.assertEqual(run.call_count, 2 if local == 'success' else 1)
                self.assertEqual(engine.job['local_success'], local == 'success')

    def test_remote_failure_preserves_local_success(self):
        engine = Engine()
        with patch.object(engine, '_run_phase', side_effect=[{'state': 'success'}, {'state': 'error'}]):
            engine.run(['local'], ['remote'])
        self.assertTrue(engine.job['local_success'])
        self.assertEqual(engine.job['state'], 'error')
        self.assertIn('local completa', engine.job['message'])

    def test_cancellation_between_phases_does_not_upload(self):
        engine = Engine()
        def finish(*args):
            engine.cancel_requested.set()
            return {'state': 'success'}
        with patch.object(engine, '_run_phase', side_effect=finish) as run:
            engine.run(['local'], ['remote'])
        self.assertEqual(run.call_count, 1)
        self.assertEqual(engine.job['state'], 'cancelled')
        self.assertTrue(engine.job['local_success'])

    def test_reconfiguration_blocked_during_transfer(self):
        engine = Engine()
        engine.job['state'] = 'running'
        with patch.object(engine.remote, 'save') as save:
            with self.assertRaises(ValueError):
                engine.configure_remote({'enabled': False, 'target': ''})
            save.assert_not_called()


class ConnectivityInstallTests(unittest.TestCase):
    def test_installs_missing_packages_and_rechecks(self):
        import install
        with patch('install.shutil.which', side_effect=[None, None, '/usr/bin/bluetoothctl', '/usr/bin/rclone']), \
             patch('install.subprocess.run', side_effect=[Mock(returncode=1), Mock(returncode=1), Mock(returncode=0), Mock(returncode=0)]), \
             patch('native_install.install_packages') as apt:
            install.check_connectivity_dependencies()
            apt.assert_called_once_with(['bluez', 'rclone', 'python3-dbus', 'python3-gi'])

    def test_dependency_failure_happens_before_stopping_services(self):
        import install
        with patch('install.check_connectivity_dependencies', side_effect=ValueError('apt failed')), \
             patch('native_install.stop') as stop:
            with self.assertRaises(ValueError):
                install.install('real', {})
            stop.assert_not_called()
