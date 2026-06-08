# Stratos

Station sol Python STRATOS avec pipeline complet extraction -> traitement -> formalisation -> visualisation web.

## Architecture

- `model/`
- `model/protocol.py` : spécification binaire, checksum, conversion en `StratosFrame`.
- `model/serial_reader.py` : extraction robuste des trames brutes depuis UART.
- `model/frame_sources.py` : abstraction des sources (`serial` réel ou `sim`/`auto`).
- `model/telemetry_service.py` : traitement temps réel, historique en mémoire, métriques lien.
- `model/logger.py` : persistance CSV horodatée.
- `controller/`
- `controller/webapp.py` : API REST (`/api/status`, `/api/latest`, `/api/history`), WebSocket live (`/ws/live`) et switch de source.
- `controller/main_console.py` : boucle console.
- `view/web_static/` : interface web live (cartes + graphiques).
- `run_web.py` : point d'entrée serveur (wrapper vers `controller.webapp`).
- `main.py` : point d'entrée console (wrapper vers `controller.main_console`).

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Lancement Web (mode réel par défaut)

```bash
python3 run_web.py
```

Puis ouvrir `http://127.0.0.1:8000`.

Le dashboard est alimenté en temps réel par WebSocket (`/ws/live`) avec reconnexion automatique.
Il inclut aussi un mode replay via chargement de CSV local et un export direct de l'historique (`/api/history.csv`).
Par défaut, la station démarre en mode `serial` (écoute réelle) et tente de se connecter à une source série.
Si aucun port valide n'est disponible, un fallback simulation reste possible via la logique `AutoFrameSource`.
Depuis l'UI, boutons `Mode simulé` et `Mode réel` permettent le switch à chaud sans redémarrer.

## Lancement Web (source série réelle)

```bash
export STRATOS_SOURCE=serial
export STRATOS_SERIAL_PORT=/dev/ttyUSB0
export STRATOS_SERIAL_BAUD=9600
python3 run_web.py
```

Sur Windows, utiliser un port de type `COM4`.

PowerShell :

```powershell
$env:STRATOS_SOURCE="serial"
$env:STRATOS_SERIAL_PORT="COM4"
python run_web.py
```

## Formats de trame

Le firmware réel envoie la trame STRATOS complète de 31 octets, big-endian. Elle contient l'ID `uint16`, l'accéléromètre, le gyroscope, la température IMU et les champs optionnels baromètre/batterie. Les champs absents sont décodés en `None`.

La station conserve aussi la compatibilité avec la trame gyro courte de 10 octets :

```text
AA ID GYR_X_H GYR_X_L GYR_Y_H GYR_Y_L GYR_Z_H GYR_Z_L CHECKSUM 55
```

- `ID` : compteur `uint8`, rollover `0..255` pour le format court
- `GYR_X/Y/Z` : `int16` big-endian en `0,1 °/s`, conversion `/ 10`
- `CHECKSUM` : XOR des octets `1..7`
- cadence attendue : `10 Hz`

L'auto-détection valide longueur, marqueurs et checksum avant extraction. La détection des pertes utilise un rollover `65536` pour la trame 31 octets et `256` pour la trame gyro courte.

L'IHM affiche le gyroscope, les angles relatifs et l'accélération en `g`. Un filtre passe-bas, une zone morte et une estimation adaptative de la gravité réduisent le bruit au repos. Le tarage IMU est automatique après 20 trames valides et peut être relancé avec le bouton `Tarer IMU`.

Une position relative courte durée est proposée avec détection d'immobilité et remise à zéro de la vitesse (ZUPT). Elle reste indicative : sans GPS, UWB, baromètre valide ou autre référence externe, une IMU seule ne permet pas de garantir une position absolue durable. Le bouton `Réinitialiser position` redéfinit l'origine.

## Variables d'environnement

- `STRATOS_SOURCE` : `serial` (défaut), `sim` ou `auto`
- `STRATOS_SIM_HZ` : fréquence simulation, défaut `10.0`
- `STRATOS_SERIAL_PORT` : port série (défaut `COM4`; surchargeable avec `/dev/ttyUSB0`, `/dev/cu.*`, ...)
- `STRATOS_SERIAL_BAUD` : défaut `9600`
- `STRATOS_SERIAL_TIMEOUT` : défaut `0.05`
- `STRATOS_LINK_TIMEOUT` : délai maximal sans paquet avant liaison perdue, défaut `1.0` seconde
- `STRATOS_HISTORY_SIZE` : profondeur historique en mémoire (défaut `600`)
- `STRATOS_LOG` : `1` pour activer CSV, `0` pour désactiver (défaut)
- `STRATOS_HOST` : défaut `127.0.0.1`
- `STRATOS_PORT` : défaut `8000`

## Métriques santé affichées

- `Rx fps` : fréquence réelle de réception.
- `Jitter ms` : variabilité des intervalles inter-trames.
- `Perte estimée %` : estimation basée sur les sauts de `frame_id`.
- `Rejet %` : trames invalides (checksum/format) sur total reçu.
- Graphes : axe Y gradué en unités physiques et axe X en temps relatif (secondes).
- Live web : fenêtre glissante de 300 points (30 s à 10 Hz) pour garder un rendu temps réel.

## Tests

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```
