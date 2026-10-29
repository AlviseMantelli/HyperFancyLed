"""Light show for the HyperSerial (AWA protocol) firmware.

Cycles through animations with a crossfade. Brightness is capped at 50%.

Keys:
  n / Right arrow  next animation
  p / Left arrow   previous animation
  a                toggle auto cycle
  + / -            brightness (max 50%)
  q                quit (turns the strip off)
"""

import argparse
import colorsys
import math
import random
import time

from led_test import build_frame, open_port, read_key

MAX_BRIGHTNESS = 0.5
GAMMA = [round((i / 255) ** 2.2 * 255) for i in range(256)]


def hsv(h, s=1.0, v=1.0):
    return colorsys.hsv_to_rgb(h % 1.0, s, v)


class Aurora:
    name = "Aurora boreale"

    def __init__(self, n):
        self.n = n

    def render(self, t, dt):
        out = []
        for i in range(self.n):
            x = i / self.n
            wave = (math.sin(x * 9 + t * 0.7) + math.sin(x * 23 - t * 1.1) * 0.6 + math.sin(x * 4 + t * 0.3)) / 2.6
            hue = 0.33 + 0.25 * (math.sin(x * 3 + t * 0.2) + 1) / 2  # green -> blue -> violet
            out.append(hsv(hue, 0.85, max(0.0, wave * 0.5 + 0.5) ** 2))
        return out


class Fire:
    name = "Fuoco"

    def __init__(self, n):
        self.n = n
        self.half = n // 2 + 1
        self.heat = [0.0] * self.half

    def render(self, t, dt):
        heat = self.heat
        for i in range(self.half):
            heat[i] = max(0.0, heat[i] - random.uniform(0, 0.09))
        for i in range(self.half - 1, 1, -1):
            heat[i] = (heat[i - 1] + heat[i - 2] * 2) / 3
        if random.random() < 0.6:
            j = random.randrange(min(7, self.half))
            heat[j] = min(1.0, heat[j] + random.uniform(0.6, 1.0))
        flame = [self.color(h) for h in heat]
        # Burns from both ends towards the middle.
        return flame[: (self.n + 1) // 2] + flame[: self.n // 2][::-1]

    @staticmethod
    def color(h):
        if h < 0.33:
            return (h * 3, 0.0, 0.0)
        if h < 0.66:
            return (1.0, (h - 0.33) * 3 * 0.7, 0.0)
        return (1.0, 0.7 + (h - 0.66) * 0.9, (h - 0.66) * 2)


class Comets:
    name = "Comete"

    def __init__(self, n):
        self.n = n
        self.buffer = [(0.0, 0.0, 0.0)] * n
        self.comets = [
            {"pos": random.uniform(0, n), "speed": random.choice((-1, 1)) * random.uniform(40, 110), "hue": random.random()}
            for _ in range(4)
        ]

    def render(self, t, dt):
        fade = 0.86
        buf = [(r * fade, g * fade, b * fade) for r, g, b in self.buffer]
        for c in self.comets:
            c["pos"] += c["speed"] * dt
            if not 0 <= c["pos"] < self.n:
                c["speed"] = -c["speed"]
                c["pos"] = min(max(c["pos"], 0), self.n - 1)
                c["hue"] = (c["hue"] + 0.13) % 1.0
            head = int(c["pos"])
            for k in (head - 1, head, head + 1):
                if 0 <= k < self.n:
                    r, g, b = hsv(c["hue"], 0.7 if k == head else 1.0)
                    o = buf[k]
                    buf[k] = (min(1, o[0] + r), min(1, o[1] + g), min(1, o[2] + b))
        self.buffer = buf
        return buf


class Starfield:
    name = "Cielo stellato"

    def __init__(self, n):
        self.n = n
        self.stars = {}

    def render(self, t, dt):
        if random.random() < 0.5:
            self.stars[random.randrange(self.n)] = [0.0, random.uniform(0.8, 2.0), random.choice((0.0, 0.6, 0.12))]
        out = [(0.0, 0.01, 0.05)] * self.n
        for i, star in list(self.stars.items()):
            star[0] += dt * star[1]
            if star[0] >= 2:
                del self.stars[i]
                continue
            level = math.sin(star[0] / 2 * math.pi)
            out[i] = hsv(star[2], 0.25, level)
        return out


class Plasma:
    name = "Plasma arcobaleno"

    def __init__(self, n):
        self.n = n

    def render(self, t, dt):
        out = []
        for i in range(self.n):
            x = i / self.n
            v = math.sin(x * 10 + t) + math.sin(x * 17 - t * 1.3) + math.sin((x + t * 0.1) * 30)
            out.append(hsv(v / 6 + t * 0.05, 1.0, 0.6 + 0.4 * math.sin(v + t)))
        return out


class Ocean:
    name = "Onde dell'oceano"

    def __init__(self, n):
        self.n = n

    def render(self, t, dt):
        out = []
        for i in range(self.n):
            x = i / self.n
            swell = (math.sin(x * 12 - t * 1.6) + 1) / 2
            crest = max(0.0, math.sin(x * 12 - t * 1.6 + 0.4)) ** 12
            r, g, b = hsv(0.55 + 0.06 * math.sin(x * 5 + t * 0.4), 1.0, 0.25 + 0.75 * swell)
            out.append((min(1, r + crest), min(1, g + crest), min(1, b + crest)))
        return out


class Fury:
    name = "Furia"

    def __init__(self, n):
        self.n = n
        self.start = None
        self.flash = 0.0
        self.next_flash = 0.0

    def render(self, t, dt):
        if self.start is None:
            self.start = t
            self.next_flash = t + random.uniform(1.5, 3.0)
        age = t - self.start

        # Double heartbeat that speeds up over 15 s, then starts over.
        bpm = 60 + 110 * ((age % 15) / 15) ** 2
        phase = (age * bpm / 60) % 1.0
        beat = math.exp(-((phase - 0.05) / 0.04) ** 2) + 0.6 * math.exp(-((phase - 0.25) / 0.05) ** 2)

        # Lightning: full strip flash with a jittery decay, max ~1 every 1.5 s.
        if t >= self.next_flash:
            self.flash = 1.0
            self.next_flash = t + random.uniform(1.5, 4.0)
        self.flash = max(0.0, self.flash - dt * 4)
        strike = self.flash * random.uniform(0.6, 1.0) if self.flash > 0 else 0.0

        out = []
        for i in range(self.n):
            x = i / self.n
            # Boiling blood: never below 40% (before gamma) so every LED stays visibly lit.
            boil = (math.sin(x * 31 + t * 5) + math.sin(x * 13 - t * 3.3) + math.sin(x * 57 + t * 8.1)) / 3
            level = 0.4 + 0.2 * (boil + 1) / 2 + 0.4 * beat
            r, g, b = min(1.0, level), 0.02 * level, 0.05 * level * (1 - beat)
            out.append((min(1.0, r + strike), min(1.0, g + strike * 0.75), min(1.0, b + strike)))
        return out


ANIMATIONS = [Aurora, Fire, Comets, Starfield, Plasma, Ocean, Fury]


def to_bytes(pixels, brightness, swap_rg):
    frame = []
    for r, g, b in pixels:
        r, g, b = (GAMMA[int(max(0.0, min(1.0, c)) * brightness * 255)] for c in (r, g, b))
        frame.append((g, r, b) if swap_rg else (r, g, b))
    return frame


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--baud", type=int, default=2000000)
    parser.add_argument("--leds", type=int, default=219)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--duration", type=float, default=20, help="seconds per animation in auto mode")
    parser.add_argument("--no-swap", action="store_true", help="do not swap red/green (strip is GRB)")
    args = parser.parse_args()

    port = open_port(args.port, args.baud)
    brightness = MAX_BRIGHTNESS
    auto = True
    index = 0
    current = ANIMATIONS[index](args.leds)
    previous, fade_start = None, 0.0
    switched_at = last = time.monotonic()
    last_status = None

    print(__doc__)
    try:
        while True:
            now = time.monotonic()
            dt, last = now - last, now

            key = read_key()
            step = 0
            if key in ("n", "right") or (auto and now - switched_at > args.duration):
                step = 1
            elif key in ("p", "left"):
                step = -1
            elif key == "a":
                auto = not auto
            elif key == "+":
                brightness = min(MAX_BRIGHTNESS, brightness + 0.05)
            elif key == "-":
                brightness = max(0.05, brightness - 0.05)
            elif key == "q":
                break

            if step:
                index = (index + step) % len(ANIMATIONS)
                previous, fade_start = current, now
                current = ANIMATIONS[index](args.leds)
                switched_at = now

            pixels = current.render(now, dt)
            if previous is not None:
                mix = min(1.0, (now - fade_start) / 1.5)
                old = previous.render(now, dt)
                pixels = [tuple(a * (1 - mix) + b * mix for a, b in zip(o, c)) for o, c in zip(old, pixels)]
                if mix >= 1.0:
                    previous = None

            port.write(build_frame(to_bytes(pixels, brightness, not args.no_swap)))

            status = f"{index + 1}/{len(ANIMATIONS)} {current.name:<20} luminosita' {brightness:.0%}  auto: {'si' if auto else 'no'}"
            if status != last_status:
                print("\r" + status.ljust(70), end="", flush=True)
                last_status = status

            time.sleep(max(0.0, 1 / args.fps - (time.monotonic() - now)))
    except KeyboardInterrupt:
        pass
    finally:
        port.write(build_frame([(0, 0, 0)] * args.leds))
        port.flush()
        port.close()
        print("\nStriscia spenta, porta chiusa.")


if __name__ == "__main__":
    main()
