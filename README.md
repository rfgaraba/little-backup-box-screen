# Little Backup Box · pantalla táctil

Interfaz en español para una pantalla horizontal de **480 × 320**, con cuatro pestañas fijas: Estado, Copiar, Archivos y Ajustes. Botones de al menos 48 px, listas de dos elementos por página y flujo Origen → Destino → Confirmar → Progreso → Resultado. Ninguna vista necesita desplazamiento.

## Ejecutar en modo demo

Requiere Python 3.10 o posterior; el servidor no necesita dependencias externas.

```sh
python server.py
```

Abrir http://127.0.0.1:8080 con el navegador a 480 × 320. El modo DEMO está identificado y no copia archivos. El trabajo continúa al cambiar de pestaña y al recargar la página; su estado reside en el servidor. Reiniciar el servidor pierde el estado y los ajustes de sesión.

## Motor real en Raspberry Pi

Instalar primero [Little Backup Box](https://github.com/outdoorbits/little-backup-box) siguiendo sus instrucciones. Esta aplicación reutiliza su `backup.py`; no implementa un motor de copia alternativo ni modifica su instalación.

1. Copiar `config.example.json` a `config.local.json` y ajustar `engine_dir` al directorio real que contiene `backup.py`.
2. Configurar los orígenes y destinos. `engine` admite `camera`, `anyusb`, `usb`, `internal` y `nvme` para origen; `usb`, `internal` y `nvme` para destino. Son perfiles configurados, no un inventario de dispositivos conectados. Reemplazar los UUID de ejemplo por los reales; `preset` usa el formato de identificador del motor. Identificadores distintos son obligatorios cuando ambos perfiles tienen el mismo tipo.
3. Ajustar `files_root` a la carpeta montada que se desea explorar. El navegador de archivos es de solo lectura, paginado y no sigue enlaces simbólicos.
4. Ejecutar `python3 server.py --config config.local.json` con los permisos necesarios para la instalación del motor. El servidor escucha únicamente en loopback. Usar un navegador local en modo kiosco, por ejemplo `chromium --kiosk http://127.0.0.1:8080` con la resolución del sistema fijada a 480 × 320.

El adaptador pasa argumentos como una lista, sin shell, conserva el origen y desactiva movimiento secundario, renombrado, modificación EXIF, miniaturas y apagado. Checksum se puede activar o desactivar en Ajustes → Copia; se activa por defecto. No hay botón de cancelación porque detener solo el proceso principal puede dejar transferencias hijas activas.

**Limitaciones de la integración inicial:** no está validada en hardware real. El motor controla el montaje y la espera de dispositivos; no se informa un porcentaje real porque su CLI no ofrece aquí un contrato estable de progreso. Mientras ejecuta se muestra un indicador indeterminado. Un código de salida 0 se muestra como «revisar registro», no como copia verificada. La salida de proceso se guarda en `.runtime/engine.log`; consultar también el registro de respaldo propio de Little Backup Box. No ejecutar simultáneamente la interfaz original, autorun u otra instancia: el bloqueo de esta aplicación cubre solo sus propios trabajos. No reiniciar el servidor durante una copia real; el proceso podría seguir activo.

Contrato CLI revisado contra el commit upstream `5e3c5f0120d7e4aa4d26a3e0e6f19a04b301b3c5`. El prototipo anterior se usó como referencia de navegación. La licencia GPL-3.0 existente se conserva.

## Instalador para Raspberry Pi OS

El instalador requiere Linux con systemd y Python 3.10 o posterior. Instala únicamente esta interfaz; no descarga ni instala el motor original, el entorno gráfico, Chromium ni los controladores de la pantalla. La resolución de 480 × 320 debe estar configurada en el sistema.

Para generar el paquete desde este repositorio:

```sh
python tools/package_installer.py
```

Copiar `dist/little-backup-box-screen-installer.zip` a la Raspberry Pi, por ejemplo con SCP, y ejecutar allí:

```sh
python3 -m zipfile -e little-backup-box-screen-installer.zip .
cd little-backup-box-screen
python3 install.py --dry-run
sudo bash install.sh
```

Esto instala en modo **demo** y habilita el arranque del servicio al encender la Raspberry Pi. Abrir http://127.0.0.1:8080 desde el navegador local. No inicia copias automáticamente.

Para usar el motor real, instalar Little Backup Box, preparar los dispositivos y ajustar las rutas y UUID del archivo de configuración:

```sh
cp config.example.json config.local.json
nano config.local.json
python3 install.py --mode real --config config.local.json --dry-run
sudo bash install.sh --mode real --config config.local.json
```

El instalador comprueba que existan `backup.py`, el intérprete y la carpeta de archivos; rechaza UUID de ejemplo e identificadores duplicados. El modo demo usa un usuario temporal de systemd. El modo real ejecuta el servicio como root para permitir las operaciones del motor, como en su interfaz original. La aplicación escucha solo en `127.0.0.1`.

Archivos instalados:

- Aplicación: `/opt/little-backup-box-screen`.
- Configuración: `/etc/little-backup-box-screen/config.json`.
- Registro del motor: `/var/lib/little-backup-box-screen/engine.log`.
- Servicio: `little-backup-box-screen.service`.

Para actualizar, extraer un paquete nuevo y ejecutar otra vez `sudo bash install.sh`: conserva el modo y la configuración existentes. Si hay un respaldo activo, un puerto ocupado por otra instancia o un servicio activo cuyo estado no puede leerse, el instalador se detiene antes de cambiar los archivos. Evitar iniciar respaldos durante la actualización. Para cambiar una configuración existente se requiere `--config archivo.json --replace-config`; guarda la versión anterior en `config.previous.json`. Solo conserva la última copia anterior.

Administrar el servicio:

```sh
systemctl status little-backup-box-screen
journalctl -u little-backup-box-screen -n 50
# Reiniciar solo cuando no hay una copia en curso:
sudo systemctl restart little-backup-box-screen
# Deshabilitar el arranque automático y detenerlo:
sudo systemctl disable --now little-backup-box-screen
```

La instalación conserva los archivos del motor original. El servicio y sus procesos hijos se detienen juntos; parar o reiniciar durante una transferencia la interrumpe. Para iniciar la pantalla en modo kiosco, usar `chromium --kiosk http://127.0.0.1:8080` en la sesión gráfica local. El instalador deja el arranque del navegador a la configuración del escritorio que uses.

`--dry-run` funciona también en Windows, no requiere sudo y no escribe archivos ni inicia servicios. Verifica el contenido de la configuración, pero las rutas Linux solo se comprueban al instalar. El instalador tiene pruebas automatizadas con un sistema de archivos temporal y llamadas a systemd simuladas; falta la prueba de instalación en una Raspberry Pi real.

## Validación

```sh
python -m unittest discover -s tests
npm install
npx playwright install chromium
# Con el servidor demo activo:
npm run test:ui
```

Las pruebas del adaptador comprueban argumentos seguros, rechazo de trabajos duplicados, resultados prudentes y confinamiento de rutas. Las pruebas visuales recorren las pestañas, paginación, detalles, ajustes, respaldo y errores; verifican desbordes, límites de pantalla y tamaño táctil. Las capturas se guardan en `test-results/`.
