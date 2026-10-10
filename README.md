# Little Backup Box · pantalla táctil

Interfaz en español para una pantalla horizontal de **480 × 320**, con cuatro pestañas fijas: Estado, Copiar, Archivos y Ajustes. Botones de al menos 48 px, listas de dos elementos por página y inicio en Backup con detección automática y selección manual Origen → Destino → Confirmar → Progreso → Resultado. Ninguna vista necesita desplazamiento.

## Instalación directa desde el repositorio

Con Little Backup Box ya instalado y el controlador de pantalla funcionando:

```sh
git clone https://github.com/rfgaraba/little-backup-box-screen.git
cd little-backup-box-screen
sudo bash install.sh
```

Una instalación nueva usa el motor real y genera su configuración: busca `backup.py` en `/var/www/html/little-backup-box`, `/opt/little-backup-box`, `/home/*/little-backup-box`, `/root/little-backup-box` y junto a este repositorio. No requiere conectar discos ni escribir UUID. Los orígenes y destinos se descubren al conectarlos; si hay varios candidatos se seleccionan en la pantalla. La microSD del sistema queda excluida y la copia empieza al tocar Backup.

Elige el primer puerto libre entre 8080 y 8100 y usa el framebuffer si hay uno solo. Si hay varios, indicar `--framebuffer /dev/fb1` (con el dispositivo correcto). Si el motor está en otra carpeta, indicar `--engine-dir /ruta/al/little-backup-box`. Si no se encuentra el motor, informa el problema; para probar sin copias reales, usar `--mode demo`.

El instalador detecta las dependencias faltantes e instala con `apt-get update` y `apt-get install -y` solamente las necesarias: `python3-pyqt6` para la pantalla nativa y `util-linux` si falta `lsblk` en modo real. Después vuelve a comprobarlas, incluido el plugin Qt LinuxFB. Requiere conexión a los repositorios si faltan paquetes; si apt falla, muestra el error y no detiene ni reconfigura los servicios de la aplicación. `--dry-run` solo informa los paquetes que se comprobarán y no ejecuta apt. El controlador del LCD debe estar funcionando previamente; el instalador no modifica su arranque.

Para actualizar: `git pull` y `sudo bash install.sh`. Conserva el modo, las rutas, los perfiles opcionales, la pantalla y el puerto instalados. Si antes instalaste en demo, cambiar a real con `sudo bash install.sh --mode real`. `--config` queda disponible para instalaciones personalizadas; `sources` y `destinations` pueden estar vacíos y los UUID solo se necesitan para perfiles manuales opcionales.

## Raspberry Pi OS Lite: pantalla nativa SPI

El enfoque para Raspberry Pi 5 (4 GB, sistema en microSD) con Raspberry Pi OS Lite de 64 bits y pantalla MHS35 es una **aplicación nativa Python + Qt**, sin Chromium, escritorio ni monitor HDMI. `native.py` dibuja mediante Qt LinuxFB en el framebuffer de la pantalla SPI y consulta el servicio local `server.py`. El servicio conserva el motor Little Backup Box, los trabajos y sus registros; cerrar o reiniciar solo la interfaz no cancela una copia. Wi-Fi puede usarse para administrar por SSH; Ajustes → Wi-Fi administra las redes mediante Comitup, el componente opcional de Little Backup Box. No añade transferencias inalámbricas al motor.

La compatibilidad del controlador MHS35 con la Pi 5 y tu kernel debe comprobarse en el equipo. [LCD-show/MHS35-show](https://github.com/goodtft/LCD-show/blob/master/MHS35-show) incluye ajustes X11, HDMI y, según la versión, framebuffer copying. Haber ejecutado ese script no garantiza que el framebuffer SPI ni el táctil estén disponibles para Qt. El instalador de esta aplicación no ejecuta LCD-show ni modifica el arranque o los controladores.

Primero, por SSH desde la carpeta del proyecto:

```sh
python3 tools/display_probe.py
```

Buscá el framebuffer identificado como la pantalla SPI y su tamaño 480 × 320. **No asumir que es `/dev/fb1`**: puede variar según el controlador. Si no aparece o solo aparece la salida de otra pantalla, hay que resolver el controlador antes de instalar la interfaz; no se selecciona HDMI como alternativa automática.

Instalar Qt y probar manualmente (reemplazar `/dev/fb1` por el dispositivo identificado):

```sh
sudo apt update
sudo apt install python3-pyqt6
# Terminal SSH 1: servidor demo, sin copias reales
python3 server.py
# Terminal SSH 2: pantalla, sin navegador ni escritorio
sudo env QT_QPA_PLATFORM=linuxfb:fb=/dev/fb1 QT_QPA_FB_HIDECURSOR=1 python3 native.py
```

Si hay una sesión X11, un servicio fbcp o una consola dibujando sobre el mismo framebuffer, debe dejar de hacerlo antes de esta prueba. No deshabilitar servicios a ciegas: comprobar qué inicia LCD-show en esa instalación. La calibración de `/etc/X11/xorg.conf.d/99-calibration.conf` no se aplica a Qt sin X11. Qt usa las entradas Linux mediante libinput/evdev; consultar [Qt: entradas en Linux embebido](https://doc.qt.io/qt-6/inputs-linux-device.html).

Una vez comprobados imagen y táctil, cerrar las dos pruebas manuales e instalar con arranque automático:

```sh
python3 install.py --display native --framebuffer /dev/fb1 --dry-run
sudo bash install.sh --display native --framebuffer /dev/fb1
```

Una instalación nueva usa el motor real detectado automáticamente. Para probar sin motor, añadir `--mode demo`. La interfaz se ejecuta como usuario temporal con acceso a los grupos `video` e `input`; el motor conserva sus permisos existentes. Las actualizaciones sin opciones conservan la interfaz y el framebuffer instalados. Una instalación nueva usa pantalla nativa por defecto y detecta el framebuffer si hay uno solo. Para usar solo el servidor web, indicar `--display web`.

El servicio de pantalla es independiente del servicio del motor:

```sh
systemctl status little-backup-box-display
journalctl -u little-backup-box-display -n 50
# Reinicia solo la interfaz; el trabajo permanece en el servidor
sudo systemctl restart little-backup-box-display
```

Para ajustar el táctil, se puede crear `/etc/little-backup-box-screen/display.env`; el instalador lo conserva.

En instalaciones sin `display.env`, el instalador reconoce el framebuffer `fb_ili9486` de 480 × 320 junto al `ADS7846 Touchscreen` y crea el perfil libinput de orientación y calibración comprobado en nuestra Raspberry Pi. Conserva cualquier archivo existente sin modificarlo. El perfil corresponde a esta orientación horizontal; otros paneles o montajes pueden requerir su propia calibración. Para este hardware, el backend evdev de Qt 6.8.2 de Debian leyó límites 0–0 y generó coordenadas inválidas, por lo que el perfil utiliza libinput.

Por ejemplo, **solo si Qt usa libinput**, una matriz de identidad (no corrige ninguna rotación; no reemplazar con ella el perfil calibrado):

```ini
QT_QPA_LIBINPUT_TOUCH_MATRIX="1 0 0 0 1 0"
```

La matriz real depende de la orientación y la calibración del panel. Para evdev, Qt ofrece `QT_QPA_EVDEV_TOUCHSCREEN_PARAMETERS` con el dispositivo y los parámetros admitidos. No se inventa una calibración antes de probar el hardware.

Para previsualizar la interfaz nativa en un equipo con escritorio, instalar PyQt6, iniciar `server.py` y ejecutar `python native.py --windowed`. La interfaz nativa y la instalación sobre el LCD real aún requieren validación en la Raspberry Pi.

## Ejecutar en modo demo

Requiere Python 3.10 o posterior; el servidor no necesita dependencias externas.

```sh
python server.py
```

Abrir http://127.0.0.1:8080 con el navegador a 480 × 320. El modo DEMO está identificado y no copia archivos. El trabajo continúa al cambiar de pestaña y al recargar la página; su estado reside en el servidor. Reiniciar el servidor pierde el estado y los ajustes de sesión.

## Motor real en Raspberry Pi

Instalar primero [Little Backup Box](https://github.com/outdoorbits/little-backup-box) siguiendo sus instrucciones. Esta aplicación reutiliza su `backup.py`; no implementa un motor de copia alternativo ni modifica su instalación.

1. Copiar `config.example.json` a `config.local.json` y ajustar `engine_dir` al directorio real que contiene `backup.py`.
2. Dejar `sources` y `destinations` vacíos para detectar las particiones USB/SD conectadas con `lsblk`, excluyendo el disco del sistema. Opcionalmente agregar perfiles manuales: `engine` admite `camera`, `anyusb`, `usb`, `internal` y `nvme` para origen; `usb`, `internal` y `nvme` para destino. En esos perfiles, `preset` usa el identificador del motor, por ejemplo `--uuid UUID-REAL`. Identificadores distintos son obligatorios cuando ambos perfiles tienen el mismo tipo.
3. Ajustar `files_root` a la carpeta montada que se desea explorar. El navegador de archivos es de solo lectura, paginado y no sigue enlaces simbólicos.
4. Ejecutar `python3 server.py --config config.local.json` con los permisos necesarios para la instalación del motor. El servidor escucha únicamente en loopback. En Raspberry Pi OS Lite, iniciar la interfaz nativa como se indica arriba. En un sistema con escritorio también se puede usar un navegador local en modo kiosco, por ejemplo `chromium --kiosk http://127.0.0.1:8080`.

El adaptador pasa argumentos como una lista, sin shell, conserva el origen y desactiva movimiento secundario, renombrado, modificación EXIF, miniaturas y apagado. Checksum se puede activar o desactivar en Ajustes → Copia; se activa por defecto. No hay botón de cancelación porque detener solo el proceso principal puede dejar transferencias hijas activas.

**Limitaciones de la integración inicial:** no está validada en hardware real. El motor controla el montaje y la espera de dispositivos; no se informa un porcentaje real porque su CLI no ofrece aquí un contrato estable de progreso. Mientras ejecuta se muestra un indicador indeterminado. Un código de salida 0 se muestra como «revisar registro», no como copia verificada. La salida de proceso se guarda en `.runtime/engine.log`; consultar también el registro de respaldo propio de Little Backup Box. No ejecutar simultáneamente la interfaz original, autorun u otra instancia: el bloqueo de esta aplicación cubre solo sus propios trabajos. No reiniciar el servidor durante una copia real; el proceso podría seguir activo.

Contrato CLI revisado contra el commit upstream `5e3c5f0120d7e4aa4d26a3e0e6f19a04b301b3c5`. El prototipo anterior se usó como referencia de navegación. La licencia GPL-3.0 existente se conserva.

## Instalador para Raspberry Pi OS

El instalador requiere Linux con systemd y Python 3.10 o posterior. Instala esta interfaz, las dependencias de sistema faltantes y configura su arranque automático; el motor original y el controlador de pantalla deben estar instalados previamente. La resolución de 480 × 320 debe estar configurada en el sistema.

Para generar el paquete desde este repositorio:

```sh
python tools/package_installer.py
```

Copiar `dist/little-backup-box-screen-installer.zip` a la Raspberry Pi, por ejemplo con SCP, y ejecutar allí:

```sh
python3 -m zipfile -e little-backup-box-screen-installer.zip .
cd little-backup-box-screen
python3 install.py --display native --framebuffer /dev/fb1 --dry-run
sudo bash install.sh --display native --framebuffer /dev/fb1
```

Esto instala en modo **real** en una instalación nueva y habilita el arranque del servicio al encender la Raspberry Pi; para probar sin motor, añadir `--mode demo`. La pantalla nativa se abre automáticamente. Con `--display web`, abrir la URL local informada por el instalador desde el navegador local. Abre Backup al iniciar la pantalla; no inicia copias automáticamente.

La configuración manual es opcional. Para personalizar las rutas del motor o agregar perfiles fijos:

```sh
cp config.example.json config.local.json
nano config.local.json
python3 install.py --mode real --config config.local.json --display native --framebuffer /dev/fb1 --dry-run
sudo bash install.sh --mode real --config config.local.json --display native --framebuffer /dev/fb1
```

El instalador comprueba que existan `backup.py`, el intérprete y la carpeta de archivos; rechaza UUID de ejemplo e identificadores duplicados. El modo demo usa un usuario temporal de systemd. El modo real ejecuta el servicio como root para permitir las operaciones del motor, como en su interfaz original. La aplicación escucha solo en `127.0.0.1`.

Archivos instalados:

- Aplicación: `/opt/little-backup-box-screen`.
- Configuración: `/etc/little-backup-box-screen/config.json`.
- Registro del motor: `/var/lib/little-backup-box-screen/engine.log`.
- Servicio: `little-backup-box-screen.service`.
- Pantalla nativa (por defecto): `little-backup-box-display.service`, con ajustes opcionales en `/etc/little-backup-box-screen/display.env`.

Si el puerto 8080 está ocupado, elegir otro con `--port`; el servidor y la pantalla nativa usarán el mismo puerto:

```sh
python3 install.py --display native --framebuffer /dev/fb1 --port 8081 --dry-run
sudo bash install.sh --display native --framebuffer /dev/fb1 --port 8081
```

Para cambiar una instalación demo a real, añadir `--mode real`; no hace falta `--config`. Para ejecutar sin instalar, usar `python3 server.py --port 8081` (demo) o agregar `--config config.local.json` (real), y `native.py --port 8081` con los ajustes Qt correspondientes. La URL web será `http://127.0.0.1:8081`.

Para actualizar desde el repositorio, ejecutar `git pull` y luego `sudo bash install.sh`; si se usa un paquete, extraer la versión nueva primero. El instalador conserva el modo, la configuración, la pantalla y el puerto existentes. Si hay un respaldo activo, un puerto ocupado por otra instancia o un servicio activo cuyo estado no puede leerse, el instalador se detiene antes de cambiar los archivos. Al cambiar de puerto, comprueba el respaldo en el puerto anterior y la disponibilidad del nuevo. Evitar iniciar respaldos durante la actualización. Para cambiar una configuración existente se requiere `--config archivo.json --replace-config`; guarda la versión anterior en `config.previous.json`. Solo conserva la última copia anterior.

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

`--dry-run` no requiere sudo y no escribe archivos ni inicia servicios. En Windows usar `--mode demo --framebuffer /dev/fb1` o una configuración explícita con `--config`; la detección automática del motor y del framebuffer requiere la Raspberry Pi. Verifica el contenido de la configuración, pero las rutas Linux solo se comprueban al instalar. El instalador tiene pruebas automatizadas con un sistema de archivos temporal y llamadas a systemd simuladas; falta la prueba de instalación en una Raspberry Pi real.

## Validación

```sh
python -m unittest discover -s tests
npm install
npx playwright install chromium
# Con el servidor demo activo:
npm run test:ui
```

Las pruebas del adaptador comprueban argumentos seguros, rechazo de trabajos duplicados, resultados prudentes y confinamiento de rutas. Las pruebas visuales recorren las pestañas, paginación, detalles, ajustes, respaldo y errores; verifican desbordes, límites de pantalla y tamaño táctil. Las capturas se guardan en `test-results/`.

## Backup al conectar dispositivos

La pantalla principal consulta los dispositivos cada segundo. Una única tarjeta SD reconocida o unidad marcada como extraíble por Linux se propone como origen y un único disco USB no extraíble como destino; al estar ambos presentes se habilita **Backup**. La copia empieza al tocar el botón. Si se desconecta un dispositivo detectado, la selección se actualiza. Nunca se propone como dispositivo el disco que contiene `/`, `/boot` o `/boot/firmware`, ni se permite copiar entre particiones del mismo disco detectado.

La microSD del sistema no es un origen de fotos. Para respaldar otra tarjeta se necesita un lector. La detección usa el tipo MMC, el indicador de medio extraíble o el modelo del lector; una memoria USB también puede marcarse como extraíble. Algunos lectores USB no informan que contienen una SD: usar **Seleccionar manual** o configurar su UUID como origen `anyusb` para reconocerlo en las próximas conexiones. Se requiere un sistema de archivos con UUID. Si hay varios candidatos, se conserva la selección manual. Los perfiles manuales pueden esperar un dispositivo desconectado, según el comportamiento del motor original.

## Wi-Fi desde la pantalla

La barra superior muestra un icono Wi-Fi con intensidad de señal, estado de conexión y marca de desconexión. Se actualiza cada cinco segundos y funciona aunque Comitup no esté instalado; indica la conexión local, no comprueba acceso a Internet. Ajustes → Info es la primera opción y muestra el nombre del dispositivo, la IP y la MAC de la interfaz de red principal.

Al iniciar la pantalla nativa se oculta el cursor de la consola Linux y se desactiva su parpadeo, además de ocultar el puntero de Qt. El ajuste se aplica al iniciar el servicio y no requiere modificar el arranque del sistema.

**Ajustes → Wi-Fi** muestra estado, red conectada y nombre del hotspot. Permite elegir una red visible o escribir un SSID oculto e ingresar la contraseña mediante un teclado táctil, con mayúsculas, números y símbolos. Comitup guarda las redes para futuras conexiones.

Seleccionar Comitup al instalar el motor Little Backup Box e instalar `python3-dbus` para el intérprete del servicio (`sudo apt install python3-dbus`). Esta interfaz detecta si Comitup no está disponible y lo informa; el modo demo no cambia la red.

El botón **Hotspot** activa un punto de acceso manual sin borrar redes ni contraseñas guardadas. Se pausa temporalmente Comitup y se activa un perfil independiente de NetworkManager, con SSID `little-backup-box-screen`, contraseña generada y DHCP compartido. La pantalla muestra la contraseña y la IP reales. **Volver a Wi-Fi** desactiva ese perfil y reactiva Comitup, que vuelve a intentar conectarse a las redes conocidas. Mientras el hotspot manual está activo se interrumpe la conexión Wi-Fi del adaptador elegido. No cambia Ethernet ni deshabilita Comitup para próximos arranques: después de reiniciar el sistema vuelve el comportamiento automático. Este hotspot manual no usa el portal cautivo de Comitup; para acceder a Little Backup Box desde otro equipo usar la IP mostrada y el puerto de su instalación original. Se requieren `nmcli`, NetworkManager y permisos root del servicio real. Si falla la activación, se intenta reactivar Comitup.

Referencias: [instalación de Little Backup Box](https://github.com/outdoorbits/little-backup-box), [Comitup](https://davesteele.github.io/comitup/) y [API D-Bus de Comitup](https://davesteele.github.io/comitup/man/comitup.pdf).

El instalador habilita con systemd tanto el servidor como la pantalla nativa para iniciar al encender la Raspberry Pi. Identificar primero el framebuffer SPI con `python3 tools/display_probe.py`: `/dev/fb1` es solamente un ejemplo. Se necesita `python3-pyqt6` y un controlador de pantalla funcional.
Referencia para el hotspot manual: [NetworkManager / nmcli](https://networkmanager.dev/docs/api/latest/nmcli.html).
