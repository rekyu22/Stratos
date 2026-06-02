# CONTEXT STRATOS -- Référence pour agent IA

Document de référence destiné à un agent IA prenant en charge le développement de la station sol Python du **Projet STRATOS**. Il contient toutes les informations nécessaires pour comprendre le système, modifier les fichiers existants ou en créer de nouveaux.

---

## 1. Présentation du projet

**Projet STRATOS** est un module de télémétrie embarqué sur drone quadricoptère, développé dans un cadre scolaire (cours Electronique Numérique). Le système acquiert des données de vol, les encode dans une trame binaire et les transmet sans fil vers un PC via liaison radio 433 MHz.

**Auteurs :** Téo GIROLA et Lucas RIGOULET

**Drone cible :** E88 (Cpolebev) -- batterie Li-Ion 1 cellule 3,7 V 1800 mAh, moteurs 816 brushless, dimensions 25x25x5,5 cm.

**Objectifs du démonstrateur :**
- Acquisition temps réel à 10 Hz : accélération, vitesse angulaire, altitude barométrique, températures, tension batterie
- Transmission sans fil drone vers PC via HC-12 (433 MHz, UART transparent)
- Visualisation et journalisation sur PC via application Python

---

## 2. Architecture matérielle

```
Batterie Li-Ion 3,7 V (3,0 V -- 4,2 V)
    |
Régulateur LDO 3,3 V (dropout <= 0,3 V)
    |
STM32G431KB (NUCLEO-G431KB)
    |-- I2C (400 kHz) --> MPU-6050  (addr 0x68) -- accél. + gyro + temp
    |-- I2C (400 kHz) --> BMP280    (addr 0x76) -- pression + temp + altitude
    |-- ADC 12 bits   --> Pont diviseur R1/R2   -- tension batterie
    |-- UART 9600 bps --> HC-12 433 MHz         -- émission radio

HC-12 433 MHz (drone)
    |
    ~  (liaison RF simplex, sans acquittement)
    |
HC-12 433 MHz (station sol) --> adaptateur CP2104 USB-TTL --> PC
    |
Application Python (station sol)
```

**Composants clés :**

| Composant | Module | Interface | Remarque critique |
|---|---|---|---|
| MCU | STM32G431KB (NUCLEO-G431KB) | -- | Tensions 3,3 V uniquement |
| IMU | MPU-6050 (GY-521 ARCELI) | I2C 0x68 | **DESTRUCTION si 5 V sur VCC/SDA/SCL** |
| Barometre | BMP280 | I2C 0x76 | Hors flux hélices obligatoire |
| Radio émission | HC-12 433 MHz | UART 9600 bps | Simplex, pas d'acquittement |
| Radio réception | HC-12 + CP2104 | USB/UART | Station sol PC |
| ADC batterie | Pont diviseur R1=10k R2=22k | ADC 12 bits | V_ADC_max = 2,89 V < 3,3 V |

**Batterie :** Li-Ion 1 cellule (pas LiPo). Plage 3,0 V (vide) -- 4,2 V (plein). Nominale 3,7 V.

---

## 3. Protocole de trame

### 3.1 Format général

La trame est **binaire, longueur fixe de 31 octets**, émise à **10 Hz** (toutes les 100 ms).

```
[STX][ID][ACC_X][ACC_Y][ACC_Z][GYR_X][GYR_Y][GYR_Z][TEMP_IMU][PRESSION][TEMP_BMP][ALTITUDE][V_BAT][CHECKSUM][ETX]
```

### 3.2 Champ par champ

| Champ | Taille | Type C | Unité brute | Conversion vers physique | Remarque |
|---|---|---|---|---|---|
| STX | 1 octet | -- | -- | -- | Toujours `0xAA` |
| ID | 2 octets | `uint16_t` | -- | -- | Numéro de trame, rollover 0--65535 |
| ACC_X | 2 octets | `int16_t` | mg | `/ 1000.0` => g | Signed big-endian |
| ACC_Y | 2 octets | `int16_t` | mg | `/ 1000.0` => g | Signed big-endian |
| ACC_Z | 2 octets | `int16_t` | mg | `/ 1000.0` => g | En vol stationnaire ~= +1000 mg |
| GYR_X | 2 octets | `int16_t` | 0,1 deg/s | `/ 10.0` => deg/s | Signed big-endian |
| GYR_Y | 2 octets | `int16_t` | 0,1 deg/s | `/ 10.0` => deg/s | Signed big-endian |
| GYR_Z | 2 octets | `int16_t` | 0,1 deg/s | `/ 10.0` => deg/s | Signed big-endian |
| TEMP_IMU | 2 octets | `int16_t` | 0,1 degC | `/ 10.0` => degC | Température interne MPU-6050 |
| PRESSION | 4 octets | `uint32_t` | Pa | `/ 100.0` => hPa | ~101325 Pa au niveau de la mer |
| TEMP_BMP | 2 octets | `int16_t` | 0,01 degC | `/ 100.0` => degC | Température ambiante BMP280 |
| ALTITUDE | 4 octets | `int32_t` | cm | `/ 100.0` => m | Altitude relative au décollage, signée |
| V_BAT | 2 octets | `uint16_t` | mV | `/ 1000.0` => V | Plage attendue : 3000--4200 mV |
| CHECKSUM | 1 octet | `uint8_t` | -- | -- | XOR de tous les octets ID à V_BAT |
| ETX | 1 octet | -- | -- | -- | Toujours `0x55` |

**Décompte :** 1 + 2 + 6 + 6 + 2 + 4 + 2 + 4 + 2 + 1 + 1 = **31 octets**

### 3.3 Endianness et format struct Python

Tous les champs multi-octets sont en **big-endian**.

Format `struct.unpack` à appliquer sur les octets 1 à 28 (index DATA_START=1, DATA_END=29) :

```python
FRAME_FORMAT = ">H hhhhhh h I h i H"
# H  = uint16  -> ID
# h  = int16   -> ACC_X, ACC_Y, ACC_Z, GYR_X, GYR_Y, GYR_Z
# h  = int16   -> TEMP_IMU
# I  = uint32  -> PRESSION
# h  = int16   -> TEMP_BMP
# i  = int32   -> ALTITUDE
# H  = uint16  -> V_BAT
```

### 3.4 Calcul du checksum

XOR de tous les octets de données, du premier octet de ID jusqu'au dernier octet de V_BAT (octets index 1 à 28 inclus dans la trame de 31 octets) :

```python
checksum = 0
for byte in raw[1:29]:
    checksum ^= byte
# Comparer avec raw[29]
```

### 3.5 Sentinelle capteur absent

Quand un capteur I2C ne répond pas, le firmware substitue la valeur `0xFFFF` dans le champ correspondant. Côté Python, un champ dont la valeur brute `& 0xFFFF == 0xFFFF` doit être traité comme `None` (capteur absent). Pour PRESSION c'est `0xFFFFFFFF`, pour ALTITUDE c'est `0x7FFFFFFF`.

### 3.6 Exemple de trame valide (trame #42, vol stationnaire à 1,5 m)

```
AA 00 2A 00 0A FF F6 03 E8 00 05 FF FB 00 00 00 DC 00 01 8A 0A 08 AC 00 00 00 96 0F 3C 6B 55
```

Décodé :
- ID = 42
- ACC : X=+0,010 g, Y=-0,010 g, Z=+1,000 g
- GYR : X=+0,5 deg/s, Y=-0,5 deg/s, Z=0,0 deg/s
- TEMP_IMU = 22,0 degC
- PRESSION = 100874 Pa = 1008,74 hPa
- TEMP_BMP = 22,20 degC
- ALTITUDE = +1,50 m
- V_BAT = 3,900 V
- CHECKSUM = 0x6B

---

## 4. Architecture des fichiers Python

Le projet station sol est découpé en 4 fichiers, chacun avec une responsabilité unique.

```
stratos_station/
    protocol.py       -- parsing, décodage, dataclass StratosFrame
    serial_reader.py  -- lecture port série, buffering, extraction trame brute
    logger.py         -- journalisation CSV horodatée
    main.py           -- point d'entrée, boucle principale, affichage console
```

### 4.1 `protocol.py`

**Responsabilité :** tout ce qui concerne le format de trame. Aucune dépendance à du matériel ou à des fichiers.

**Constantes exposées :**
- `FRAME_LENGTH = 31`
- `STX = 0xAA`
- `ETX = 0x55`
- `SENSOR_ABSENT = 0xFFFF`
- `FRAME_FORMAT = ">H hhhhhh h I h i H"`
- `DATA_START = 1`, `DATA_END = 29`

**Dataclass exposée :** `StratosFrame`

```python
@dataclass
class StratosFrame:
    frame_id:  int
    acc_x:     Optional[float]   # g
    acc_y:     Optional[float]   # g
    acc_z:     Optional[float]   # g
    gyr_x:     Optional[float]   # deg/s
    gyr_y:     Optional[float]   # deg/s
    gyr_z:     Optional[float]   # deg/s
    temp_imu:  Optional[float]   # degC
    pression:  Optional[float]   # hPa
    temp_bmp:  Optional[float]   # degC
    altitude:  Optional[float]   # m (relatif au décollage)
    v_bat:     Optional[float]   # V
```

Tous les champs sont `Optional[float]` : la valeur est `None` si le capteur correspondant était absent lors de la mesure.

**Fonction exposée :** `parse_frame(raw: bytes) -> Optional[StratosFrame]`

Retourne `None` si la longueur est incorrecte, si STX/ETX ne correspondent pas, ou si le checksum est invalide.

### 4.2 `serial_reader.py`

**Responsabilité :** lire le port série et extraire des trames brutes (`bytes` de 31 octets). Ne connaît pas le contenu de la trame.

**Classe exposée :** `SerialReader`

```python
reader = SerialReader(port="COM4", baudrate=9600, timeout=1.0)
reader.open()
raw = reader.read_frame()   # retourne bytes ou None
reader.close()
```

**Mécanisme interne :** buffer `bytearray` qui accumule les octets reçus. La méthode `_extract_frame()` cherche `0xAA`, attend 31 octets, vérifie que le 31e est `0x55`, avance le buffer. Gère les réceptions fragmentées (inévitables à 9600 bps).

### 4.3 `logger.py`

**Responsabilité :** écriture CSV horodatée des trames décodées.

**Classe exposée :** `TelemetryLogger`

```python
logger = TelemetryLogger()
logger.open()          # crée logs/stratos_YYYYMMDD_HHMMSS.csv
logger.log(frame)      # append une ligne, flush immédiat
logger.close()
```

Le dossier `logs/` est créé automatiquement. Le `flush()` est immédiat après chaque ligne pour garantir l'intégrité en cas de crash.

**En-têtes CSV :** `timestamp, frame_id, acc_x_g, acc_y_g, acc_z_g, gyr_x_dps, gyr_y_dps, gyr_z_dps, temp_imu_c, pression_hpa, temp_bmp_c, altitude_m, v_bat_v`

Les valeurs `None` sont écrites `N/A` dans le CSV.

### 4.4 `main.py`

**Responsabilité :** point d'entrée, orchestration, affichage console.

**Constantes à adapter selon l'environnement :**
```python
SERIAL_PORT    = "COM4"       # Windows: "COMx" -- Linux: "/dev/ttyUSB0"
SERIAL_BAUD    = 9600
LINK_TIMEOUT_S = 2.0          # secondes avant affichage "LIAISON PERDUE"
```

**Comportement de la boucle principale :**
1. `SerialReader.read_frame()` -- si `None`, vérifie le timeout de liaison
2. `parse_frame(raw)` -- si `None`, incrémente `frames_rejected`
3. `display_frame(frame)` + `logger.log(frame)` -- si trame valide

L'affichage console utilise `\033[2J\033[H` pour effacer le terminal (émulation temps réel, pas de dépendance externe).

---

## 5. Paramètres de communication série

| Paramètre | Valeur |
|---|---|
| Baudrate | 9600 bps |
| Bits de données | 8 |
| Parité | Aucune |
| Bits de stop | 1 |
| Contrôle de flux | Aucun |
| Port Windows | COMx (vérifier gestionnaire de périphériques) |
| Port Linux | /dev/ttyUSB0 ou /dev/ttyACM0 |

---

## 6. Dépendances Python

Dépendance externe unique :

```
pyserial
```

Installation : `pip install pyserial`

Dépendances standard (incluses dans Python 3.x) : `struct`, `dataclasses`, `typing`, `csv`, `os`, `datetime`, `time`.

---

## 7. Règles de conception à respecter

- Aucun commentaire dans le code. Tout ce qui doit être expliqué l'est dans ce document ou dans le code lui-même par les noms de variables et de fonctions.
- `protocol.py` ne doit avoir aucune dépendance extérieure sauf `struct`, `dataclasses`, `typing`.
- `serial_reader.py` ne doit pas connaître la signification des octets qu'il transmet.
- `logger.py` ne reçoit que des `StratosFrame` déjà décodées (valeurs physiques), jamais des octets bruts.
- `main.py` est le seul fichier autorisé à orchestrer les trois autres.
- Toute nouvelle fonctionnalité d'affichage (graphique, IHM) s'ajoute dans `main.py` sans modifier les autres modules.
- Les champs `None` doivent toujours être gérés explicitement (ne jamais supposer qu'un capteur est présent).

---

## 8. Valeurs physiques attendues en conditions normales

| Grandeur | Valeur typique au sol | Valeur typique en vol stationnaire |
|---|---|---|
| ACC_Z | ~+1,000 g (gravité) | ~+1,000 g |
| ACC_X, ACC_Y | ~0 g | faible, < 0,1 g |
| GYR_X, GYR_Y, GYR_Z | ~0 deg/s | < 50 deg/s |
| PRESSION | ~1013 hPa (niveau mer) | légèrement inférieure selon altitude |
| TEMP_IMU | 25 -- 45 degC (chauffe en fonctionnement) | idem |
| TEMP_BMP | temperature ambiante | idem |
| ALTITUDE | 0,00 m (référence décollage) | 0 -- 30 m typique |
| V_BAT | 3,7 -- 4,2 V (batterie chargée) | décroît avec l'usage |

---

## 9. Points critiques et pièges connus

- **Li-Ion != LiPo :** la batterie du drone E88 est Li-Ion 1 cellule. La plage 3,0--4,2 V est différente d'une LiPo classique. Ne pas confondre dans les calculs de seuil.
- **MPU-6050 et 5 V :** le module GY-521 ARCELI supporte 3,3 V uniquement sur le bus I2C. 5 V détruit le composant de manière irréversible.
- **Trame fragmentée :** à 9600 bps, un appel `serial.read()` peut retourner moins de 31 octets. Le buffer dans `serial_reader.py` est indispensable.
- **Checksum sur données uniquement :** le XOR porte sur les octets ID à V_BAT (index 1 à 28), **pas** sur STX ni ETX.
- **Altitude relative :** l'altitude dans la trame est relative au point de décollage (P0 enregistré au démarrage du firmware), pas une altitude absolue.
- **Simplex :** le HC-12 n'émet que depuis le drone. Aucun acquittement n'est possible. Les trames perdues ne sont pas récupérables.
- **0xFFFF = capteur absent :** cette valeur sentinelle est insérée par le firmware quand un capteur I2C ne répond pas. Elle ne correspond à aucune mesure physique valide.
