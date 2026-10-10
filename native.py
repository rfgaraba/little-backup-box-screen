"""Native 480x320 touch client. The backup service owns all transfer jobs."""
import argparse
import json
import sys
from urllib.parse import urlencode

from PyQt6.QtCore import QByteArray, Qt, QTimer, QUrl
from PyQt6.QtGui import QFontMetrics, QPainter, QPen, QColor
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QVBoxLayout, QWidget, QDialog, QLineEdit, QGridLayout,
)

BASE = 'http://127.0.0.1:8080'


class WifiIndicator(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(26, 20)
        self.state, self.signal = 'unavailable', None

    def set_state(self, wifi):
        self.state, self.signal = wifi.get('state', 'unavailable'), wifi.get('signal')
        self.setAccessibleName({'connected': 'Wi-Fi conectado', 'connecting': 'Wi-Fi conectando',
                                'disconnected': 'Wi-Fi desconectado'}.get(self.state, 'Wi-Fi no disponible'))
        self.setToolTip(self.accessibleName())
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        connected = self.state == 'connected'
        level = 3 if self.signal is None else max(1, min(3, (self.signal + 32) // 33))
        for i, radius in enumerate((6, 10, 14), 1):
            color = '#79dcc6' if connected and i <= level else '#53718d'
            painter.setPen(QPen(QColor(color), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(13 - radius, 19 - radius, radius * 2, radius * 2, 45 * 16, 90 * 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#79dcc6' if connected else '#53718d'))
        painter.drawEllipse(11, 16, 4, 4)
        if not connected:
            painter.setPen(QPen(QColor('#edf4fa'), 2))
            if self.state == 'connecting':
                painter.drawLine(22, 12, 22, 16)
                painter.drawPoint(22, 19)
            else:
                painter.drawLine(3, 2, 23, 19)


class TouchKeyboard(QDialog):
    """Text entry that also works on LinuxFB without a desktop keyboard."""
    def __init__(self, title, parent, secret=False):
        super().__init__(parent)
        self.setFixedSize(480, 320)
        self.pages = ['abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                      '0123456789!@#$%^&*()-_=+[]{}', ';:,.?/\\|`~\'"<>']
        self.page = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        layout.addWidget(QLabel(title))
        self.field = QLineEdit()
        self.field.setFixedHeight(36)
        if secret:
            self.field.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.field)
        self.keys = QGridLayout()
        self.keys.setSpacing(2)
        layout.addLayout(self.keys)
        row = QHBoxLayout()
        for label, action in [('Borrar', self.field.backspace), ('Espacio', lambda: self.field.insert(' ')),
                              ('Otros', self.next_page), ('Cancelar', self.reject), ('Aceptar', self.accept)]:
            b = QPushButton(label)
            b.setFixedHeight(48)
            b.clicked.connect(lambda checked=False, a=action: a())
            row.addWidget(b)
        layout.addLayout(row)
        self.draw_keys()

    def draw_keys(self):
        while self.keys.count():
            self.keys.takeAt(0).widget().deleteLater()
        for i in range(27):
            char = self.pages[self.page][i:i + 1]
            b = QPushButton(char)
            b.setFixedHeight(48)
            b.setEnabled(bool(char))
            b.clicked.connect(lambda checked=False, c=char: self.field.insert(c))
            self.keys.addWidget(b, i // 9, i % 9)

    def next_page(self):
        self.page = (self.page + 1) % len(self.pages)
        self.draw_keys()

    @classmethod
    def read(cls, title, parent, secret=False):
        dialog = cls(title, parent, secret)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return dialog.field.text(), accepted


class TouchButton(QPushButton):
    def __init__(self, text):
        super().__init__(text)
        self.full_text = text
        self.setAccessibleName(text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setText(QFontMetrics(self.font()).elidedText(
            self.full_text, Qt.TextElideMode.ElideRight, max(1, self.width() - 20)))


class Screen(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Little Backup Box')
        self.setFixedSize(480, 320)
        self.network = QNetworkAccessManager(self)
        self.status = None
        self.devices = {'sources': [], 'destinations': []}
        self.tab, self.step, self.page = 'Copiar', -1, 0
        self.wifi = {}
        self.info = {}
        self.info_pending = False
        self.wifi_ticks = 0
        self.source = self.destination = self.detail = self.setting = None
        self.path, self.error = '', ''
        self.files = {'entries': [], 'page': 0, 'pages': 1}
        self.pending = False
        self.polling = False
        self.file_request = 0
        self.files_loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)
        self.mode = QLabel('CONECTANDO')
        self.mode.setFixedHeight(20)
        header = QHBoxLayout()
        header.addWidget(self.mode, 1)
        self.wifi_indicator = WifiIndicator()
        header.addWidget(self.wifi_indicator)
        layout.addLayout(header)
        self.body = QWidget()
        self.content = QVBoxLayout(self.body)
        self.content.setContentsMargins(0, 0, 0, 0)
        self.content.setSpacing(4)
        layout.addWidget(self.body, 1)
        nav = QHBoxLayout()
        nav.setSpacing(4)
        for name in ('Estado', 'Copiar', 'Archivos', 'Ajustes'):
            nav.addWidget(self.button(name, lambda n=name: self.switch(n)))
        layout.addLayout(nav)
        self.setStyleSheet('''
            QWidget { background: #101c2a; color: #edf4fa; font-size: 15px; }
            QPushButton { background: #253b50; border: 1px solid #53718d;
                border-radius: 6px; padding: 2px 8px; }
            QPushButton:pressed { background: #397b97; }
            QPushButton:disabled { color: #7d8b98; }
            QProgressBar { border: 1px solid #53718d; text-align: center; }
            QProgressBar::chunk { background: #39bba6; }
        ''')
        self.render()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    def button(self, text, action):
        b = TouchButton(text)
        b.setFixedHeight(48)
        b.setMinimumWidth(48)
        b.clicked.connect(lambda checked=False: action())
        return b

    def request(self, path, callback, data=None, failure=None):
        request = QNetworkRequest(QUrl(BASE + path))
        request.setTransferTimeout(60000 if path == '/api/wifi' else 5000)
        if data is None:
            reply = self.network.get(request)
        else:
            request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, 'application/json')
            reply = self.network.post(request, QByteArray(json.dumps(data).encode()))

        def finished():
            try:
                raw = bytes(reply.readAll())
                if reply.error() != reply.NetworkError.NoError and not raw:
                    raise ValueError('Sin conexión con el servidor')
                payload = json.loads(raw)
                if reply.error() != reply.NetworkError.NoError:
                    raise ValueError(payload.get('error', 'Sin conexión con el servidor'))
                callback(payload)
            except (ValueError, TypeError, KeyError) as exc:
                self.error = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError) else 'Respuesta inválida del servidor'
                if failure:
                    failure()
                self.render()
            finally:
                reply.deleteLater()
        reply.finished.connect(finished)

    def refresh(self):
        if self.polling:
            return
        self.polling = True
        self.wifi_ticks += 1
        if self.wifi_ticks == 1 or self.wifi_ticks % 5 == 0:
            self.refresh_info()
        if self.setting == 'Wi-Fi' and self.wifi_ticks % 5 == 0:
            def wifi_done(data):
                if data != self.wifi:
                    self.wifi = data
                    self.render()
            self.request('/api/wifi', wifi_done)

        def status(data):
            self.polling = False
            changed = data != self.status or self.error == 'Sin conexión con el servidor'
            self.status = data
            if self.error == 'Sin conexión con el servidor':
                self.error = ''
            if changed:
                self.render()
            self.request('/api/devices', self.set_devices)
        self.request('/api/status', status, failure=lambda: setattr(self, 'polling', False))

    def set_devices(self, data):
        if data == self.devices:
            return
        self.devices = data
        if self.step == 2 and any(d and d['id'].startswith('auto:') and not any(x['id'] == d['id'] for x in data[g])
                                  for d, g in ((self.source, 'sources'), (self.destination, 'destinations'))):
            self.step = -1
        self.render()

    def switch(self, tab):
        self.tab, self.page = tab, 0
        self.detail = self.setting = None
        self.error = ''
        if tab == 'Archivos':
            self.load_files()
        self.render()

    def label(self, text):
        label = QLabel()
        metrics = QFontMetrics(label.font())
        lines = text.splitlines()[:2] or ['']
        label.setText('\n'.join(metrics.elidedText(line, Qt.TextElideMode.ElideRight, 450) for line in lines))
        label.setAccessibleName(text)
        label.setFixedHeight(22 * len(lines))
        label.setTextFormat(Qt.TextFormat.PlainText)
        self.content.addWidget(label)

    def add(self, text, action):
        self.content.addWidget(self.button(text, action))

    def row(self, actions):
        row = QHBoxLayout()
        for text, action, enabled in actions:
            b = self.button(text, action)
            b.setEnabled(enabled)
            row.addWidget(b)
        self.content.addLayout(row)

    def clear(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
            elif item.layout():
                self.clear(item.layout())

    def render(self):
        self.clear(self.content)
        if self.error:
            self.label(self.error)
            self.add('Reintentar', self.retry)
        elif self.status is None:
            self.label('Conectando con el servicio de respaldo…')
        else:
            self.mode.setText('DEMO · no copia archivos' if self.status['demo'] else 'Little Backup Box')
            if self.tab == 'Estado' or (self.tab == 'Copiar' and
                    (self.status['job']['state'] == 'running' or self.step == 3)):
                self.job_view()
            elif self.tab == 'Copiar':
                self.copy_view()
            elif self.tab == 'Archivos':
                self.files_view()
            else:
                self.settings_view()
        self.content.addStretch()

    def retry(self):
        self.error = ''
        self.refresh()
        if self.tab == 'Archivos':
            self.load_files()
        self.render()

    def job_view(self):
        job = self.status['job']
        self.label(job['message'])
        if job['state'] == 'running':
            bar = QProgressBar()
            if job['progress'] is None:
                bar.setRange(0, 0)
            else:
                bar.setValue(job['progress'])
            self.content.addWidget(bar)
        else:
            self.add('Nuevo respaldo', self.new_job)

    def new_job(self):
        self.tab, self.step, self.page = 'Copiar', -1, 0
        self.source = self.destination = None
        self.render()

    def choose(self, device):
        if self.step == 0:
            self.source = device
        else:
            self.destination = device
        self.step += 1
        self.page = 0
        self.render()

    def copy_view(self):
        if self.step == -1:
            auto = self.devices.get('automatic', {})
            self.source = next((d for d in self.devices['sources'] if d['id'] == auto.get('source')), None)
            self.destination = next((d for d in self.devices['destinations'] if d['id'] == auto.get('destination')), None)
            self.label('Backup · conectar SD y disco USB')
            self.label('Origen: ' + (self.source['label'] if self.source else 'sin detectar') + '\nDestino: ' +
                       (self.destination['label'] if self.destination else 'sin detectar'))
            self.row([
                ('Seleccionar manual', self.manual_copy, True),
                ('Simular' if self.status['demo'] else 'Backup', self.start_job,
                 bool(self.source and self.destination) and not self.pending),
            ])
            self.label(self.devices.get('detection_error', 'Elegí manualmente si no se detecta la tarjeta.'))
            return
        self.label(('1 · Elegir origen', '2 · Elegir destino', '3 · Confirmar')[self.step])
        if self.step < 2:
            group = 'sources' if self.step == 0 else 'destinations'
            devices = [d for d in self.devices[group]
                       if self.step == 0 or d['id'] != self.source['id']]
            pages = max(1, (len(devices) + 1) // 2)
            self.page = min(self.page, pages - 1)
            for device in devices[self.page * 2:self.page * 2 + 2]:
                self.add(device['label'], lambda d=device: self.choose(d))
            if not devices:
                self.label('No hay perfiles disponibles.')
            self.row([
                ('Volver', lambda: self.back_step(), self.step > 0),
                ('Anterior', lambda: self.change_page(-1), self.page > 0),
                ('Siguiente', lambda: self.change_page(1), self.page < pages - 1),
            ])
        else:
            self.label('De: ' + self.source['label'] + '\nA: ' + self.destination['label'])
            self.label('No se copiarán archivos.' if self.status['demo'] else 'Copiar sin borrar el origen.')
            self.row([
                ('Volver', self.back_step, not self.pending),
                ('Simular' if self.status['demo'] else 'Iniciar copia', self.start_job, not self.pending),
            ])

    def back_step(self):
        self.step = max(0, self.step - 1)
        self.page = 0
        self.render()

    def manual_copy(self):
        self.step, self.page = 0, 0
        self.render()

    def change_page(self, delta):
        self.page += delta
        if self.tab == 'Archivos':
            self.load_files()
        else:
            self.render()

    def start_job(self):
        if self.pending:
            return
        self.pending = True
        self.render()

        def done(data):
            self.pending = False
            self.status, self.step = data, 3
            self.render()
        self.request('/api/backup', done,
                     {'source': self.source['id'], 'destination': self.destination['id']},
                     failure=lambda: setattr(self, 'pending', False))

    def load_files(self):
        self.file_request += 1
        generation = self.file_request
        self.files_loading = True
        self.render()

        def done(data):
            if generation == self.file_request:
                self.files_loading = False
                self.files, self.page = data, data['page']
                self.render()
        self.request('/api/files?' + urlencode({'path': self.path, 'page': self.page}), done,
                     failure=lambda: setattr(self, 'files_loading', False))

    def open_entry(self, entry):
        if entry['directory']:
            self.path = '/'.join(filter(None, (self.path, entry['name'])))
            self.page = 0
            self.load_files()
        else:
            self.detail = entry
            self.render()

    def up(self):
        self.path = self.path.rpartition('/')[0]
        self.page = 0
        self.load_files()

    def files_view(self):
        if self.files_loading:
            self.label('Leyendo carpeta…')
            return
        if self.detail:
            self.label(self.detail['name'])
            self.label(f"Tamaño: {self.detail['size'] / 1000000:.1f} MB · solo lectura")
            self.add('Volver', lambda: self.switch('Archivos'))
            return
        self.label(QFontMetrics(self.font()).elidedText(
            self.path or 'Archivos del respaldo', Qt.TextElideMode.ElideMiddle, 450))
        for entry in self.files['entries']:
            self.add(('▸ ' if entry['directory'] else '') + entry['name'],
                     lambda e=entry: self.open_entry(e))
        if not self.files['entries']:
            self.label('Carpeta vacía')
        self.row([
            ('Subir', self.up, bool(self.path)),
            ('Anterior', lambda: self.change_page(-1), self.page > 0),
            ('Siguiente', lambda: self.change_page(1), self.page < self.files['pages'] - 1),
        ])

    def settings_view(self):
        self.label(self.setting or 'Ajustes')
        if not self.setting:
            self.row([('Info', lambda: self.show_setting('Info'), True),
                      ('Copia', lambda: self.show_setting('Copia'), True)])
            self.row([('Wi-Fi', lambda: self.show_setting('Wi-Fi'), True),
                      ('Sistema', lambda: self.show_setting('Sistema'), True)])
        else:
            if self.setting == 'Info':
                self.label('Dispositivo: ' + self.info.get('hostname', 'Consultando…'))
                self.label('IP: ' + (self.info.get('ip') or 'Sin dirección IP'))
                self.label('MAC: ' + (self.info.get('mac') or 'No disponible'))
                self.label('Interfaz: ' + (self.info.get('interface') or 'Sin conexión'))
            elif self.setting == 'Copia':
                self.label('Checksum · se aplica al próximo respaldo')
                self.add('Activado' if self.status['checksum'] else 'Desactivado', self.toggle_checksum)
            elif self.setting == 'Wi-Fi':
                if not self.wifi.get('available'):
                    self.label(self.wifi.get('message', 'Consultando Wi-Fi…'))
                    self.add('Actualizar', lambda: self.show_setting('Wi-Fi'))
                else:
                    self.label(self.wifi['state'] + ' · ' + self.wifi['connection'] + '\nHotspot: ' + self.wifi['hotspot'])
                    if self.wifi.get('forced'):
                        self.label('Contraseña: ' + self.wifi.get('password', '') + '\nIP: ' + self.wifi.get('address', ''))
                    self.row([('Volver a Wi-Fi' if self.wifi.get('forced') else 'Conectar red',
                               self.resume_wifi if self.wifi.get('forced') else self.connect_wifi, True),
                              ('Hotspot', self.hotspot_wifi, not self.wifi.get('forced'))])
            elif self.setting == 'Pantalla':
                self.label('480 × 320 · pantalla SPI\nInterfaz nativa Qt · sin escritorio')
            else:
                self.label('DEMO' if self.status['demo'] else 'Little Backup Box · motor CLI')
                self.label('Ajustes de copia: solo esta sesión')
            self.add('Volver', lambda: self.show_setting(None))

    def show_setting(self, name):
        self.setting = name
        if name == 'Info':
            self.refresh_info()
        if name == 'Wi-Fi':
            def done(data):
                self.wifi = data
                self.render()
            self.request('/api/wifi', done)
        self.render()

    def refresh_info(self):
        if self.info_pending:
            return
        self.info_pending = True
        def done(data):
            self.info_pending = False
            self.info = data
            self.wifi_indicator.set_state(data.get('wifi', {}))
            if self.setting == 'Info':
                self.render()
        def failed():
            self.info_pending = False
            self.wifi_indicator.set_state({})
        self.request('/api/info', done, failure=failed)

    def connect_wifi(self):
        networks = [n['ssid'] for n in self.wifi.get('networks', [])]
        if networks:
            picker = QDialog(self)
            picker.setFixedSize(480, 320)
            layout = QVBoxLayout(picker)
            title = QLabel('Elegir red Wi-Fi')
            layout.addWidget(title)
            selected = []
            page = [0]
            buttons = []
            def draw():
                for i, b in enumerate(buttons):
                    index = page[0] * 2 + i
                    b.full_text = networks[index] if index < len(networks) else ''
                    b.setText(b.full_text)
                    b.setAccessibleName(b.full_text)
                    b.setEnabled(index < len(networks))
            for i in range(2):
                def choose(index=i):
                    selected.append(networks[page[0] * 2 + index])
                    picker.accept()
                b = self.button('', choose)
                buttons.append(b)
                layout.addWidget(b)
            row = QHBoxLayout()
            def change(delta):
                page[0] = max(0, min((len(networks) - 1) // 2, page[0] + delta))
                draw()
            for label, action in [('Anterior', lambda: change(-1)), ('Siguiente', lambda: change(1)),
                                  ('Otra red', picker.accept), ('Volver', picker.reject)]:
                row.addWidget(self.button(label, action))
            layout.addLayout(row)
            draw()
            if picker.exec() != QDialog.DialogCode.Accepted:
                return
            ssid, ok = (selected[0], True) if selected else TouchKeyboard.read('Red Wi-Fi (SSID)', self)
        else:
            ssid, ok = TouchKeyboard.read('Red Wi-Fi (SSID)', self)
        if not ok or not ssid:
            return
        password, ok = TouchKeyboard.read('Contraseña (vacía si es abierta)', self, True)
        if ok:
            self.request('/api/wifi', lambda _: self.show_setting('Wi-Fi'),
                         {'action': 'connect', 'ssid': ssid, 'password': password})

    def hotspot_wifi(self):
        dialog = QDialog(self)
        dialog.setFixedSize(480, 320)
        layout = QVBoxLayout(dialog)
        message = QLabel('Activar hotspot. Se interrumpirá la conexión Wi-Fi actual; tus redes y contraseñas quedan guardadas. Podés volver a Wi-Fi cuando quieras.')
        message.setWordWrap(True)
        layout.addWidget(message)
        layout.addWidget(self.button('Cancelar', dialog.reject))
        layout.addWidget(self.button('Activar hotspot', dialog.accept))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.request('/api/wifi', lambda _: self.show_setting('Wi-Fi'), {'action': 'hotspot'})

    def resume_wifi(self):
        self.request('/api/wifi', lambda _: self.show_setting('Wi-Fi'), {'action': 'resume'})

    def toggle_checksum(self):
        def done(data):
            self.status = data
            self.render()
        self.request('/api/settings', done, {'checksum': not self.status['checksum']})


def main():
    global BASE
    parser = argparse.ArgumentParser(description='Pantalla táctil nativa de Little Backup Box')
    parser.add_argument('--windowed', action='store_true', help='Previsualizar en un escritorio')
    parser.add_argument('--port', type=int, default=8080, help='Puerto del servidor local')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('El puerto debe estar entre 1 y 65535')
    BASE = f'http://127.0.0.1:{args.port}'
    app = QApplication([sys.argv[0]])
    screen = Screen()
    if args.windowed:
        screen.show()
    else:
        screen.setCursor(Qt.CursorShape.BlankCursor)
        screen.showFullScreen()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
