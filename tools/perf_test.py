"""Frame rate and latency benchmark for the HyperSerial (AWA protocol) firmware.

1. Throughput: streams a 25% brightness rainbow at several target rates and
   reads back the firmware's own counters (frames shown / received / good).
2. Latency: sends one frame followed by a statistics request and measures the
   round trip until the answer arrives. Since the firmware handles bytes in
   order, the answer proves the frame has been parsed and handed to the LED
   driver. A request without frame is measured too, as the baseline.

The light itself is not measured: add the LED wire time printed at the end.
"""

import argparse
import re
import statistics
import time

from led_test import build_frame, open_port, render_effect

STATS_REQUEST = b"Awa\x2a\xa2\x35"
STATS_LINE = re.compile(rb"HyperHDR frames: (\d+) \(FPS\), receiv\.: (\d+), good: (\d+), incompl\.: (\d+), mem1")
BRIGHTNESS = 0.25


def dimmed_frame(count, t):
    pixels = render_effect("arcobaleno", count, None, t)
    return build_frame([tuple(int(c * BRIGHTNESS) for c in px) for px in pixels])


def request_stats(port, timeout=1.0):
    """Ask the firmware for its counters; return (show, total, good, incomplete) or None."""
    port.write(STATS_REQUEST)
    received = b""
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        received += port.read(max(1, port.in_waiting))
        match = STATS_LINE.search(received)
        if match:
            return tuple(int(v) for v in match.groups())
    return None


def throughput(port, leds, rates, seconds):
    print(f"\n== Throughput ({leds} LED, {seconds}s per prova) ==")
    print(f"{'target':>8} {'inviati/s':>10} {'mostrati':>9} {'ricevuti':>9} {'buoni':>6} {'incompl.':>9}")
    started = time.perf_counter()
    for rate in rates:
        port.reset_input_buffer()
        sent = 0
        begin = time.perf_counter()
        next_at = begin
        while time.perf_counter() - begin < seconds:
            port.write(dimmed_frame(leds, time.perf_counter() - started))
            sent += 1
            if rate:
                next_at += 1 / rate
                while time.perf_counter() < next_at:
                    pass
        sent_rate = sent / (time.perf_counter() - begin)
        port.flush()
        stats = request_stats(port)
        label = f"{rate}" if rate else "max"
        if stats:
            show, total, good, bad = stats
            print(f"{label:>8} {sent_rate:10.1f} {show:9d} {total:9d} {good:6d} {bad:9d}")
        else:
            print(f"{label:>8} {sent_rate:10.1f}   nessuna risposta dalle statistiche")
        time.sleep(0.3)


def round_trips(port, payload, samples):
    times = []
    for _ in range(samples):
        port.reset_input_buffer()
        begin = time.perf_counter()
        port.write(payload)
        if request_stats(port):
            times.append((time.perf_counter() - begin) * 1000)
        time.sleep(0.05)  # firmware sleeps 10 ms after printing statistics
    return times


def describe(name, times):
    if not times:
        print(f"{name:>22}: nessuna risposta")
        return
    ordered = sorted(times)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    print(f"{name:>22}: min {ordered[0]:5.2f}  media {statistics.mean(ordered):5.2f}  "
          f"p95 {p95:5.2f}  max {ordered[-1]:5.2f} ms  ({len(ordered)} campioni)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--baud", type=int, default=2000000)
    parser.add_argument("--leds", type=int, default=219)
    parser.add_argument("--seconds", type=float, default=3.0)
    parser.add_argument("--samples", type=int, default=100)
    args = parser.parse_args()

    port = open_port(args.port, args.baud)
    try:
        time.sleep(0.3)
        frame_bytes = len(dimmed_frame(args.leds, 0))
        print(f"Porta {args.port}, {args.leds} LED, {frame_bytes} byte per frame, luminosita' {BRIGHTNESS:.0%}")

        throughput(port, args.leds, [30, 60, 100, 120, 144, 0], args.seconds)

        print(f"\n== Latenza andata/ritorno ==")
        describe("solo richiesta", round_trips(port, b"", args.samples))
        describe("frame + richiesta", round_trips(port, dimmed_frame(args.leds, 1.0), args.samples))

        # WS281x: 1.25 us per bit, 24 bit per LED, plus ~280 us reset (WS2815)
        wire_ms = args.leds * 24 * 1.25 / 1000 + 0.28
        print(f"\nTempo di scrittura sulla striscia: ~{wire_ms:.2f} ms -> massimo teorico ~{1000 / wire_ms:.0f} FPS")
    finally:
        port.write(build_frame([(0, 0, 0)] * args.leds))
        port.flush()
        port.close()


if __name__ == "__main__":
    main()
