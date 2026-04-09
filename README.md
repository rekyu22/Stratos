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

## Lancement Web (mode auto recommandé)

```bash
python3 run_web.py
```

Puis ouvrir `http://127.0.0.1:8000`.

Le dashboard est alimenté en temps réel par WebSocket (`/ws/live`) avec reconnexion automatique.
Il inclut aussi un mode replay via chargement de CSV local et un export direct de l'historique (`/api/history.csv`).
En mode auto (défaut), la station tente une source série puis bascule en simulation si aucun port valide n'est disponible.
Depuis l'UI, boutons `Mode simulé` et `Mode réel` permettent le switch à chaud sans redémarrer.

## Lancement Web (source série réelle)

```bash
export STRATOS_SOURCE=serial
export STRATOS_SERIAL_PORT=/dev/ttyUSB0
export STRATOS_SERIAL_BAUD=9600
python3 run_web.py
```

Sur Windows, utiliser un port de type `COM3`.

## Variables d'environnement

- `STRATOS_SOURCE` : `auto` (défaut), `sim` ou `serial`
- `STRATOS_SIM_HZ` : fréquence simulation, défaut `10.0`
- `STRATOS_SERIAL_PORT` : port série (`COM3`, `/dev/ttyUSB0`, ...)
- `STRATOS_SERIAL_BAUD` : défaut `9600`
- `STRATOS_SERIAL_TIMEOUT` : défaut `1.0`
- `STRATOS_LOG` : `1` pour activer CSV, `0` pour désactiver
- `STRATOS_HOST` : défaut `127.0.0.1`
- `STRATOS_PORT` : défaut `8000`

## Métriques santé affichées

- `Rx fps` : fréquence réelle de réception.
- `Jitter ms` : variabilité des intervalles inter-trames.
- `Perte estimée %` : estimation basée sur les sauts de `frame_id`.
- `Rejet %` : trames invalides (checksum/format) sur total reçu.

## Tests

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```
