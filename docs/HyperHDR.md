# Impostazioni HyperHDR

Configurazione lato HyperHDR per le due schede con questo firmware.

| | ESP32-C3 Super Mini | ESP32 Lolin32 |
|---|---|---|
| Porta | COM5 (USB nativa) | COM4 (CH340) |
| Env PlatformIO | `C3_SUPERMINI_WS281x_RGB` | `LOLIN32_WS2815` |
| Striscia | WS2815 12V, 219 LED, pin dati GPIO4 | WS2815, 127 LED, pin dati GPIO16 |
| FPS testati senza perdite | 120 | 144 (max ~240) |
| Latenza misurata (frame ricevuto e letto) | ~6.3 ms | ~3.8 ms |

## Dispositivo LED (LED Hardware → LED Controller)

| Campo | C3 (COM5) | Lolin32 (COM4) | Note |
|---|---|---|---|
| Tipo controller | `adalight` | `adalight` | |
| Output path | `COM5` | `COM4` | |
| Baudrate | `2000000` | `2000000` | sul C3 (USB nativa) il valore è ignorato ma lascialo così |
| AWA protocol | **attivo** | **attivo** | obbligatorio: il firmware parla solo AWA |
| ESP8266/ESP32 handshake | off | off | |
| Force serial detection | off | off | |
| Color order | **`grb`** | `grb` | sul C3 la striscia ha R e G invertiti: con `grb` qui i colori tornano giusti |
| Refresh time | `20` ms | `20` ms | vedi *Spegnimento automatico* |
| Numero LED (layout) | **219** | 127 | |
| White channel calibration | off | off | solo per strisce RGBW |

## FPS e latenza

- **Smoothing spento** = latenza minima. I LED si aggiornano alla velocità del grabber
  (oggi `systemGrabber.fps = 60`).
- **Per arrivare a 120 FPS sui LED** attiva lo smoothing con:
  - `Update frequency`: `120`
  - `Time`: corto (20-40 ms). Ogni ms aggiunge ritardo percepito.
  - Il default `30` Hz va cambiato, altrimenti limita tutto a 30 FPS.
- **Non andare sopra 120 Hz sul C3**: la striscia da 219 LED impiega ~6.9 ms a frame
  (massimo teorico ~146 FPS) e a 144 il firmware inizia a scartare frame.
  Il Lolin32 con 127 LED regge 144 senza perdite.

## Spegnimento automatico

Entrambi i firmware hanno `IDLE_OFF_TIMEOUT=5000`: se per 5 secondi non arriva un frame
valido (HyperHDR chiuso male, crash, PC bloccato o in sospensione) la striscia viene spenta.
Lo stop normale di HyperHDR manda già un frame nero e spegne subito.

- Tieni `Refresh time` **maggiore di 0 e sotto i 5000 ms** (va bene l'attuale `20`):
  serve a rimandare l'ultimo frame quando l'immagine è ferma. Con `0` e un'immagine statica
  per più di 5 s, i LED si spegnerebbero.
- Se il PC si spegne ma l'alimentatore 12V resta acceso, nessun firmware può spegnere
  la striscia: le WS2815 tengono l'ultimo colore. Serve un relè sull'alimentazione.

## Log

Quando HyperHDR chiede le statistiche, il firmware risponde con due righe, per esempio:

```
HyperHDR frames: 120 (FPS), receiv.: 120, good: 120, incompl.: 0, mem1: ..., mem2: ..., heap: ...
Idle off: 3, last frame: 17 ms ago
```

`Idle off` conta quante volte la striscia è stata spenta per inattività.

## Strumenti di test (`tools/`)

Prima chiudi HyperHDR: la porta può essere aperta da un solo programma.

```
.venv\Scripts\python.exe tools\led_test.py --port COM5 --start 219        # conteggio LED, colori
.venv\Scripts\python.exe tools\led_test.py --port COM5 --start 219 --psu  # test alimentatore
.venv\Scripts\python.exe tools\animations.py --port COM5                  # show di animazioni
.venv\Scripts\python.exe tools\perf_test.py --port COM4 --leds 127        # FPS e latenza
.venv\Scripts\python.exe tools\shutdown_test.py --port COM4 --leds 127    # spegnimento
```
