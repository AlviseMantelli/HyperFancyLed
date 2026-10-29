"""Shutdown tests: what happens to the LEDs when the host stops sending frames.

Each scenario streams a 25% rainbow, then stops the way HyperHDR (or a crash)
would. The firmware (built with IDLE_OFF_TIMEOUT) reports, together with its
statistics, how many times it blanked the strip and how long ago the last valid
frame arrived: the test checks those numbers automatically.

  1. clean stop (black frame + close)   -> black frame accepted
  2. crash (close without black frame)  -> blank after the timeout
  3. PC frozen (port open, no data)     -> blank after the timeout
  4. frame cut in half                  -> blank after the timeout (+ parser reset)
  5. static image, 1 frame per second   -> never blanked
  6. restart after idle blank           -> frames accepted again

Use --ask to also confirm each result by looking at the strip.
"""

import argparse
import re
import time

from led_test import build_frame, open_port, render_effect

BRIGHTNESS = 0.25
STATS_REQUEST = b"Awa\x2a\xa2\x35"
IDLE_LINE = re.compile(rb"Idle off: (\d+), last frame: (\d+) ms ago")


def rainbow_frame(leds, t):
    pixels = render_effect("arcobaleno", leds, None, t)
    return build_frame([tuple(int(c * BRIGHTNESS) for c in px) for px in pixels])


def black_frame(leds):
    return build_frame([(0, 0, 0)] * leds)


def stream(port, leds, seconds, fps=60):
    begin = time.perf_counter()
    while time.perf_counter() - begin < seconds:
        port.write(rainbow_frame(leds, time.perf_counter()))
        time.sleep(1 / fps)
    port.flush()


def idle_status(port):
    """Return (blank count, ms since last good frame) as reported by the firmware."""
    for _ in range(2):
        port.reset_input_buffer()
        port.write(STATS_REQUEST)
        received = b""
        deadline = time.perf_counter() + 1.0
        while time.perf_counter() < deadline:
            received += port.read(max(1, port.in_waiting))
            match = IDLE_LINE.search(received)
            if match:
                return int(match.group(1)), int(match.group(2))
    raise RuntimeError("il firmware non ha risposto con la riga 'Idle off' (manca IDLE_OFF_TIMEOUT?)")


def wait_for_blank(port, baseline, limit):
    """Poll until the blank counter moves; return ms since last frame at that moment, or None."""
    begin = time.perf_counter()
    while time.perf_counter() - begin < limit:
        count, last_ms = idle_status(port)
        if count > baseline:
            return last_ms
        time.sleep(0.1)
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--baud", type=int, default=2000000)
    parser.add_argument("--leds", type=int, default=219)
    parser.add_argument("--timeout", type=float, default=5.0, help="IDLE_OFF_TIMEOUT of the firmware, in seconds")
    parser.add_argument("--ask", action="store_true", help="also ask for a visual confirmation")
    args = parser.parse_args()

    leds, timeout_ms = args.leds, args.timeout * 1000
    results = []

    def record(name, ok, detail, question=None):
        if args.ask and question:
            ok = ok and input(f"  >> {question} [s/n] ").strip().lower() == "s"
        results.append((name, ok, detail))
        print(f"  {'OK  ' if ok else 'FAIL'}  {detail}")

    def blank_in_window(last_ms, slack_ms):
        return last_ms is not None and timeout_ms <= last_ms <= timeout_ms + slack_ms

    print("[1] Stop pulito come HyperHDR: frame nero e chiusura porta")
    port = open_port(args.port, args.baud)
    stream(port, leds, 3)
    port.write(black_frame(leds))
    port.flush()
    port.close()
    port = open_port(args.port, args.baud)
    _, last_ms = idle_status(port)
    record("1 stop pulito", last_ms < 1000, f"frame nero accettato {last_ms} ms fa", "Si sono spenti SUBITO?")
    port.close()
    time.sleep(args.timeout + 1)

    print("[2] Crash: porta chiusa senza frame nero")
    port = open_port(args.port, args.baud)
    stream(port, leds, 3)
    baseline, _ = idle_status(port)
    port.close()
    time.sleep(args.timeout + 1.5)
    port = open_port(args.port, args.baud)
    count, last_ms = idle_status(port)
    ok = count == baseline + 1 and last_ms >= timeout_ms
    record("2 crash", ok, f"spegnimenti {baseline} -> {count}, ultimo frame {last_ms} ms fa (nessun reset della scheda)",
           "Sono rimasti accesi qualche secondo e poi si sono spenti?")

    print("[3] PC bloccato: porta aperta, nessun dato")
    stream(port, leds, 3)
    baseline, _ = idle_status(port)
    last_ms = wait_for_blank(port, baseline, args.timeout + 3)
    record("3 PC bloccato", blank_in_window(last_ms, 600), f"spento dopo {last_ms} ms senza frame", "Si sono spenti da soli?")

    print("[4] Frame troncato a meta'")
    stream(port, leds, 3)
    baseline, _ = idle_status(port)
    frame = rainbow_frame(leds, 0)
    port.write(frame[: len(frame) // 2])
    port.flush()
    # Stay silent: until the parser gives up on the half frame, any query byte
    # would be eaten as pixel data.
    time.sleep(args.timeout + 2)
    count, last_ms = idle_status(port)
    record("4 frame troncato", count == baseline + 1, f"spegnimenti {baseline} -> {count}, ultimo frame valido {last_ms} ms fa",
           "Si sono spenti da soli?")

    print("[5] Immagine statica: 1 frame al secondo per 12s")
    still = rainbow_frame(leds, 0)
    port.write(still)
    baseline, _ = idle_status(port)
    worst = 0
    for _ in range(12):
        time.sleep(1)
        port.write(still)
        count, last_ms = idle_status(port)
        worst = max(worst, last_ms)
    record("5 immagine statica", count == baseline, f"spenta {count - baseline} volte, frame piu' vecchio {worst} ms",
           "Sono rimasti SEMPRE accesi?")

    print("[6] Ripartenza dopo lo spegnimento automatico")
    baseline, _ = idle_status(port)
    if wait_for_blank(port, baseline, args.timeout + 3) is None:
        record("6 ripartenza", False, "lo spegnimento automatico non e' avvenuto")
    else:
        stream(port, leds, 3)
        count, last_ms = idle_status(port)
        record("6 ripartenza", last_ms < 100 and count == baseline + 1, f"frame di nuovo accettati ({last_ms} ms fa)",
               "Si sono riaccesi con l'arcobaleno?")
    port.write(black_frame(leds))
    port.flush()
    port.close()

    print("\n== Risultato ==")
    for name, ok, detail in results:
        print(f"  {'OK  ' if ok else 'FAIL'}  {name:20} {detail}")


if __name__ == "__main__":
    main()
