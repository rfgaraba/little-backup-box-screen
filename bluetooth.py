"""BlueZ D-Bus adapter with a touch-operated pairing agent (optional on demo)."""
import threading
import uuid

ADAPTER = 'org.bluez.Adapter1'
DEVICE = 'org.bluez.Device1'
PROPERTIES = 'org.freedesktop.DBus.Properties'
AGENT = 'org.bluez.Agent1'


class Bluetooth:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.bus = None
        self.lock = threading.RLock()
        self.operation_lock = threading.Lock()
        self.init_lock = threading.Lock()
        self.prompt = None
        self.callbacks = None
        self.pairing = None
        self.connecting = None
        self.message = ''
        self.agent = None
        self.scanning = False

    def _open(self):
        with self.init_lock:
            self._open_bus()

    def _open_bus(self):
        if not self.enabled:
            raise ValueError('Bluetooth no se modifica en modo demo')
        if self.bus is None:
            try:
                import dbus
                from dbus.mainloop.glib import DBusGMainLoop, threads_init
                from gi.repository import GLib
                threads_init()
                DBusGMainLoop(set_as_default=True)
                self.dbus, self.glib = dbus, GLib
                self.bus = dbus.SystemBus()
                self.bus.add_signal_receiver(self._bluez_changed, signal_name='NameOwnerChanged',
                                             dbus_interface='org.freedesktop.DBus', arg0='org.bluez')
                self.loop = GLib.MainLoop()
                threading.Thread(target=self.loop.run, daemon=True).start()
            except Exception as exc:
                self.bus = None
                raise ValueError('Bluetooth no disponible: instalá BlueZ, python3-dbus y python3-gi') from exc

    def _bluez_changed(self, name, old, new):
        if old:
            with self.lock:
                self._clear()
                self.pairing = None
                self.connecting = None
                self.scanning = False
                if self.agent:
                    self.agent.remove_from_connection()
                    self.agent = None
                self.message = 'El servicio Bluetooth se reinició; podés reintentar'

    def _interface(self, path, interface):
        return self.dbus.Interface(self.bus.get_object('org.bluez', path), interface)

    def _objects(self):
        self._open()
        return self._interface('/', 'org.freedesktop.DBus.ObjectManager').GetManagedObjects(timeout=5)

    def status(self):
        try:
            objects = self._objects()
            path = next(p for p, interfaces in objects.items() if ADAPTER in interfaces)
            props = objects[path][ADAPTER]
            devices = []
            for p, interfaces in objects.items():
                d = interfaces.get(DEVICE)
                if d is not None and str(d.get('Adapter')) == str(path):
                    devices.append({'id': str(p), 'name': str(d.get('Alias', d.get('Address', p))),
                                    'address': str(d.get('Address', '')), 'paired': bool(d.get('Paired')),
                                    'connected': bool(d.get('Connected'))})
            devices.sort(key=lambda d: (not d['connected'], not d['paired'], d['name'].casefold()))
            with self.lock:
                prompt = dict(self.prompt) if self.prompt else None
            return {'available': True, 'powered': bool(props.get('Powered')),
                    'connected': any(d['connected'] for d in devices),
                    'discovering': bool(props.get('Discovering')), 'devices': devices,
                    'pairing': self.pairing, 'connecting': self.connecting, 'prompt': prompt,
                    'message': self.message}
        except Exception:
            return {'available': False, 'powered': False, 'connected': False, 'devices': [],
                    'message': 'Bluetooth no disponible' if self.enabled else 'Bluetooth no se modifica en modo demo'}

    def _ask(self, device, kind, reply, error, code=''):
        with self.lock:
            if self.callbacks:
                error(self._rejected())
                return
            self.prompt = {'id': uuid.uuid4().hex, 'device': str(device), 'kind': kind, 'code': str(code)}
            self.callbacks = (reply, error)

    def _rejected(self):
        return self.dbus.exceptions.DBusException('Emparejamiento rechazado', name='org.bluez.Error.Rejected')

    def _agent(self):
        if self.agent:
            return
        import dbus.service
        owner = self

        class Agent(dbus.service.Object):
            @dbus.service.method(AGENT, in_signature='', out_signature='')
            def Release(self):
                owner._clear()
                owner.agent = None
                self.remove_from_connection()

            @dbus.service.method(AGENT, in_signature='', out_signature='')
            def Cancel(self):
                owner._clear()

            @dbus.service.method(AGENT, in_signature='ou', out_signature='', async_callbacks=('reply', 'error'))
            def RequestConfirmation(self, device, passkey, reply, error):
                owner._ask(device, 'confirm', reply, error, f'{int(passkey):06}')

            @dbus.service.method(AGENT, in_signature='o', out_signature='s', async_callbacks=('reply', 'error'))
            def RequestPinCode(self, device, reply, error):
                owner._ask(device, 'pin', reply, error)

            @dbus.service.method(AGENT, in_signature='o', out_signature='u', async_callbacks=('reply', 'error'))
            def RequestPasskey(self, device, reply, error):
                owner._ask(device, 'passkey', reply, error)

            @dbus.service.method(AGENT, in_signature='o', out_signature='', async_callbacks=('reply', 'error'))
            def RequestAuthorization(self, device, reply, error):
                owner._ask(device, 'authorize', reply, error)

            @dbus.service.method(AGENT, in_signature='os', out_signature='', async_callbacks=('reply', 'error'))
            def AuthorizeService(self, device, service, reply, error):
                owner._ask(device, 'authorize', reply, error, service)

            @dbus.service.method(AGENT, in_signature='os', out_signature='')
            def DisplayPinCode(self, device, code):
                owner._display(device, code)

            @dbus.service.method(AGENT, in_signature='ouq', out_signature='')
            def DisplayPasskey(self, device, passkey, entered):
                owner._display(device, f'{int(passkey):06}')

        agent = Agent(self.bus, '/org/lbb/screen/agent')
        try:
            self._interface('/org/bluez', 'org.bluez.AgentManager1').RegisterAgent('/org/lbb/screen/agent', 'KeyboardDisplay')
        except Exception:
            agent.remove_from_connection()
            raise
        self.agent = agent

    def _display(self, device, code):
        with self.lock:
            self.prompt = {'id': uuid.uuid4().hex, 'device': str(device), 'kind': 'display', 'code': str(code)}

    def _clear(self):
        with self.lock:
            self.prompt = self.callbacks = None

    def _paired(self, path, error=None):
        with self.lock:
            self._clear()
            self.pairing = None
            self.message = 'No se pudo emparejar; podés reintentar' if error else 'Emparejado; tocá Conectar para usarlo'
            if not error:
                try:
                    self._interface(path, PROPERTIES).Set(DEVICE, 'Trusted', self.dbus.Boolean(True))
                except Exception:
                    self.message = 'Emparejado; no se pudo habilitar la reconexión automática'

    def _stop_scan(self, adapter):
        with self.lock:
            if self.scanning:
                try:
                    self._interface(adapter, ADAPTER).StopDiscovery(timeout=5)
                except Exception:
                    pass
                self.scanning = False

    def _connected(self, path, error=None):
        with self.lock:
            self.connecting = None
            self._clear()
            self.message = 'No se pudo conectar; comprobá que el dispositivo esté disponible' if error else 'Conectado'

    def apply(self, data):
        from contextlib import nullcontext
        with (nullcontext() if data.get('action') == 'respond' else self.operation_lock):
            try:
                return self._apply(data)
            except ValueError:
                raise
            except Exception as exc:
                raise ValueError('No se pudo completar la operación Bluetooth; comprobá el adaptador y el dispositivo') from exc

    def _respond(self, data):
        with self.lock:
            if not self.prompt or not self.callbacks or data.get('prompt') != self.prompt['id']:
                raise ValueError('La solicitud de emparejamiento venció')
            if not isinstance(data.get('accept'), bool):
                raise ValueError('Respuesta inválida')
            kind = self.prompt['kind']
            value = data.get('value', '')
            if data['accept']:
                if kind == 'pin' and (not isinstance(value, str) or not 1 <= len(value) <= 16):
                    raise ValueError('El PIN debe tener de 1 a 16 caracteres')
                if kind == 'passkey' and (not isinstance(value, str) or not value.isascii() or not value.isdigit() or not 1 <= len(value) <= 6):
                    raise ValueError('El código debe tener hasta 6 dígitos')
            reply, error = self.callbacks
            self._clear()
            def respond():
                if not data['accept']:
                    error(self._rejected())
                elif kind == 'pin':
                    reply(value)
                elif kind == 'passkey':
                    reply(self.dbus.UInt32(int(value)))
                else:
                    reply()
                return False
            self.glib.idle_add(respond)
            return

    def _apply(self, data):
        if data.get('action') == 'respond':
            return self._respond(data)
        objects = self._objects()
        adapter = next((p for p, interfaces in objects.items() if ADAPTER in interfaces), None)
        if adapter is None:
            raise ValueError('No hay adaptador Bluetooth')
        action = data.get('action')
        if action == 'power':
            if not isinstance(data.get('enabled'), bool):
                raise ValueError('Estado Bluetooth inválido')
            self._interface(adapter, PROPERTIES).Set(ADAPTER, 'Powered', self.dbus.Boolean(data['enabled']))
            if not data['enabled']:
                self.scanning = False
            return
        if action == 'scan':
            if not self.scanning:
                self._interface(adapter, ADAPTER).StartDiscovery(timeout=5)
                self.scanning = True
                timer = threading.Timer(20, self._stop_scan, args=(adapter,))
                timer.daemon = True
                timer.start()
            return
        path = data.get('device')
        if path not in objects or DEVICE not in objects[path] or str(objects[path][DEVICE].get('Adapter')) != str(adapter):
            raise ValueError('El dispositivo Bluetooth ya no está disponible')
        interface = self._interface(path, DEVICE)
        if action == 'pair':
            if self.pairing:
                raise ValueError('Ya hay un emparejamiento en curso')
            self._agent()
            self.pairing = path
            self.message = 'Emparejando…'
            try:
                interface.Pair(reply_handler=lambda: self._paired(path),
                               error_handler=lambda error: self._paired(path, error), timeout=90)
            except Exception:
                self.pairing = None
                raise
        elif action == 'cancel':
            interface.CancelPairing(timeout=5)
            self._clear()
        elif action == 'connect':
            if self.connecting:
                raise ValueError('Ya hay una conexión en curso')
            self._agent()
            self.connecting = path
            self.message = 'Conectando…'
            try:
                interface.Connect(reply_handler=lambda: self._connected(path),
                                  error_handler=lambda error: self._connected(path, error), timeout=30)
            except Exception:
                self.connecting = None
                raise
        elif action == 'disconnect':
            interface.Disconnect(timeout=15)
        elif action == 'remove':
            self._interface(adapter, ADAPTER).RemoveDevice(path, timeout=10)
        else:
            raise ValueError('Acción Bluetooth inválida')
