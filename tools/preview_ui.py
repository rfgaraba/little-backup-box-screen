"""Render touch layouts without starting a backup or accessing real devices."""
import os
import sys
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication
from native import Screen

app = QApplication([])
class PreviewScreen(Screen):
    def refresh(self):
        pass

screen = PreviewScreen()
screen.timer.stop()
screen.status = {'demo': False, 'job': {'state': 'idle', 'message': 'Listo', 'progress': None}, 'checksum': True}
source = {'id': 'auto:SD', 'label': 'Tarjeta SD', 'name': 'SD Card', 'disk': '/dev/sdb', 'capacity_bytes': 128e9, 'used_bytes': 8e9, 'free_bytes': 120e9}
target = {'id': 'auto:SSD', 'label': 'Extreme SSD', 'name': 'Extreme SSD', 'disk': '/dev/sda', 'capacity_bytes': 1e12, 'used_bytes': 271e9, 'free_bytes': 729e9}
screen.devices = {'sources': [source, target], 'destinations': [source, target], 'automatic': {'source': source['id'], 'destination': target['id']}}
output = Path(sys.argv[1])
output.mkdir(exist_ok=True)
screen.show()
for name in ('respaldo', 'progreso', 'exito', 'monitor'):
    if name in ('progreso', 'exito'):
        screen.step = 3
        screen.status['job'] = {'state': 'running' if name == 'progreso' else 'success', 'progress': 36.3 if name == 'progreso' else 100,
                               'message': 'Procesando archivos' if name == 'progreso' else 'Copia completada con éxito',
                               'metrics': {'write_bps': 16e6, 'disk_written_bytes': 5.9e9, 'elapsed_seconds': 884,
                                           'eta': '0:09:49', 'files_processed': 90, 'files_total': 248}}
    if name == 'monitor':
        screen.tab, screen.setting = 'Utilidades', 'Monitor'
        screen.monitor = {'cpu_percent': 23.4, 'temperature_c': 49.1, 'memory': {'used_bytes': 1.2e9, 'total_bytes': 4e9}}
    screen.render()
    app.processEvents()
    screen.grab().save(str(output / (name + '.png')))
screen.close()
