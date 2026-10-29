"""Interactive LED strip tester for the HyperSerial (AWA protocol) firmware.

Keys:
  + / Up arrow     add LEDs (step)
  - / Down arrow   remove LEDs (step)
  1 / 5 / 0        step = 1 / 10 / 100
  c                cycle color
  e                cycle effect (off / rainbow / scanner / breathe)
  w                power supply test: ALL LEDs 100% white, press again to cut
                   to black immediately (then any key resumes)
  q                quit (turns the strip off)

The last lit LED is drawn in red so it is easy to count.
"""

import argparse
import colorsys
import math
import msvcrt
import threading
import time

import serial

COLORS = [
    ("bianco", (255, 255, 255)),
    ("verde", (0, 255, 0)),
    ("blu", (0, 0, 255)),
    ("giallo", (255, 180, 0)),
    ("bianco 25%", (64, 64, 64)),
]
MARKER = (255, 0, 0)
EFFECTS = ["off", "arcobaleno", "supercar", "respiro"]


def render_effect(effect, count, color, t):
    """Return `count` pixels for the given effect at time `t` (seconds)."""
    if effect == "arcobaleno":
        pixels = []
        for i in range(count):
            r, g, b = colorsys.hsv_to_rgb((i / max(count, 1) + t * 0.2) % 1.0, 1.0, 1.0)
            pixels.append((int(r * 255), int(g * 255), int(b * 255)))
        return pixels

    if effect == "supercar":
        # Head bounces end to end leaving a fading tail.
        span = max(count - 1, 1)
        phase = (t * 60) % (2 * span)
        head = phase if phase <= span else 2 * span - phase
        pixels = []
        for i in range(count):
            level = max(0.0, 1.0 - abs(i - head) / 8)
            pixels.append(tuple(int(c * level) for c in color))
        return pixels

    if effect == "respiro":
        level = (math.sin(t * 2) + 1) / 2
        return [tuple(int(c * level) for c in color)] * count

    return [color] * (count - 1) + [MARKER]


def build_frame(pixels):
    """Encode a list of (r, g, b) tuples as an AWA protocol v1 frame."""
    count = len(pixels) - 1
    hi, lo = (count >> 8) & 0xFF, count & 0xFF
    frame = bytearray(b"Awa")
    frame += bytes((hi, lo, hi ^ lo ^ 0x55))

    fletcher1 = fletcher2 = fletcher_ext = 0
    position = 0
    for rgb in pixels:
        for value in rgb:
            frame.append(value)
            fletcher1 = (fletcher1 + value) % 255
            fletcher2 = (fletcher2 + fletcher1) % 255
            fletcher_ext = (fletcher_ext + (value ^ position)) % 255
            position = (position + 1) & 0xFF

    if fletcher_ext == 0x41:
        fletcher_ext = 0xAA
    frame += bytes((fletcher1, fletcher2, fletcher_ext))
    return bytes(frame)


def open_port(name, baud):
    """Open the serial port keeping DTR/RTS low, so the board is not reset."""
    port = serial.Serial()
    port.port, port.baudrate, port.timeout = name, baud, 0.02
    port.dtr = port.rts = False
    port.open()
    time.sleep(0.2)
    port.reset_input_buffer()
    return port


def read_device(port, stop):
    """Print whatever the firmware writes back (hello message, statistics)."""
    while not stop.is_set():
        try:
            line = port.readline()
        except serial.SerialException:
            return
        if line:
            print(f"\r[dev] {line.decode(errors='replace').rstrip()}")


def read_key():
    """Return a normalized key name, or None if nothing was pressed."""
    if not msvcrt.kbhit():
        return None
    key = msvcrt.getwch()
    if key in ("\x00", "\xe0"):  # arrow / function key prefix
        key = {"H": "up", "P": "down", "K": "left", "M": "right"}.get(msvcrt.getwch())
    return key


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--baud", type=int, default=2000000)
    parser.add_argument("--start", type=int, default=1, help="initial number of lit LEDs")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--psu", action="store_true",
                        help="power supply test only: start dark, 'w' toggles all LEDs 100%% white")
    args = parser.parse_args()

    port = open_port(args.port, args.baud)
    stop = threading.Event()
    threading.Thread(target=read_device, args=(port, stop), daemon=True).start()

    lit = max(1, args.start)
    # Frame length never shrinks, so LEDs removed with '-' are sent as black.
    total = lit
    step = 1
    color_index = 0
    effect_index = 0
    full_white = False
    blackout = args.psu
    last_status = None
    started = time.monotonic()

    print(__doc__)
    try:
        while True:
            key = read_key()
            if key == "w":
                full_white = not full_white
                if not full_white:
                    # Drop queued frames and cut to black right away.
                    port.reset_output_buffer()
                    port.write(build_frame([(0, 0, 0)] * total))
                    port.flush()
                    blackout = True
                key = None
            elif args.psu and key != "q":
                key = None
            elif key is not None and blackout:
                blackout = False

            if key in ("+", "up"):
                lit = min(4096, lit + step)
            elif key in ("-", "down"):
                lit = max(1, lit - step)
            elif key in ("1", "5", "0"):
                step = {"1": 1, "5": 10, "0": 100}[key]
            elif key == "c":
                color_index = (color_index + 1) % len(COLORS)
            elif key == "e":
                effect_index = (effect_index + 1) % len(EFFECTS)
            elif key == "q":
                break
            total = max(total, lit)

            name, color = COLORS[color_index]
            effect = EFFECTS[effect_index]
            if full_white:
                pixels = [(255, 255, 255)] * total
                status = f"!!! TEST ALIMENTATORE: {total} LED bianco 100% - premi w per spegnere !!!"
            elif blackout:
                pixels = [(0, 0, 0)] * total
                if args.psu:
                    status = f"Spento - premi w per accendere {total} LED bianco 100%, q per uscire"
                else:
                    status = "Spento dopo il test alimentatore - premi un tasto per riprendere"
            else:
                pixels = render_effect(effect, lit, color, time.monotonic() - started)
                pixels += [(0, 0, 0)] * (total - lit)
                status = f"LED accesi: {lit:4d}  (frame {total})  step: {step:3d}  colore: {name}  effetto: {effect}"
            port.write(build_frame(pixels))

            if status != last_status:
                print("\r" + status.ljust(90), end="", flush=True)
                last_status = status

            time.sleep(1 / args.fps)
    except KeyboardInterrupt:
        pass
    finally:
        port.write(build_frame([(0, 0, 0)] * total))
        port.flush()
        stop.set()
        port.close()
        print("\nStriscia spenta, porta chiusa.")


if __name__ == "__main__":
    main()
