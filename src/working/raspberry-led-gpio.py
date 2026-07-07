import time
import math
import colorsys
import threading
import signal
import sys
import board
import neopixel
import select

from evdev import InputDevice, ecodes

# ----------------------------
# CONFIG
# ----------------------------
LED_PIN = board.D18
NUM_LEDS = 30
BRIGHTNESS = 0.3

# Spezielles Event-Device für nur den LED-Button
DEVICE_PATH = "/dev/input/by-id/usb-DragonRise_Inc._Generic_USB_Joystick-event-joystick"
BUTTON_CODE = 298  # BTN_BASE5

# ----------------------------
# LED SETUP
# ----------------------------
pixels = neopixel.NeoPixel(
    LED_PIN,
    NUM_LEDS,
    brightness=BRIGHTNESS,
    auto_write=False
)

mode = 0
colorful_mode = 0
running = True
mode_lock = threading.Lock()


# ----------------------------
# CLEANUP ON EXIT
# ----------------------------
def cleanup(signum=None, frame=None):
    global running
    print("Service stopping, turning off LEDs...")
    running = False
    pixels.fill((0, 0, 0))
    pixels.show()
    sys.exit(0)


signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT, cleanup)


# ----------------------------
# HELPER
# ----------------------------
def hsv_color(h, s=1.0, v=1.0):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return int(r * 255), int(g * 255), int(b * 255)


# ----------------------------
# EFFECTS
# ----------------------------
def rainbow(step):
    for pixel in range(NUM_LEDS):
        hue = (pixel / NUM_LEDS + step) % 1.0
        pixels[pixel] = hsv_color(hue)
    pixels.show()


def breathe_outwards(t, base_hue):
    center = (NUM_LEDS - 1) / 2
    breath = (math.sin(t) + 1) / 2
    color = hsv_color(base_hue)
    for i in range(NUM_LEDS):
        dist = abs(i - center)
        falloff = max(0.0, 1.0 - (dist / center))
        brightness = breath * falloff
        r = int(color[0] * brightness)
        g = int(color[1] * brightness)
        b = int(color[2] * brightness)
        pixels[i] = (r, g, b)
    pixels.show()


def scanner(position, hue):
    pixels.fill((0, 0, 0))
    color_main = hsv_color(hue)
    pos = int(position) % NUM_LEDS
    pixels[pos] = color_main
    for offset in range(1, 6):
        fade = max(0.0, 1.0 - (offset / 6))
        r = int(color_main[0] * fade)
        g = int(color_main[1] * fade)
        b = int(color_main[2] * fade)
        if pos - offset >= 0:
            pixels[pos - offset] = (r, g, b)
        if pos + offset < NUM_LEDS:
            pixels[pos + offset] = (r, g, b)
    pixels.show()


# ----------------------------
# INPUT THREAD (nur BTN_BASE5)
# ----------------------------
def input_listener():
    global mode, colorful_mode, running
    dev = InputDevice(DEVICE_PATH)
    last_press = 0

    while running:
        r, w, x = select.select([dev], [], [], 0.01)
        if dev in r:
            try:
                for event in dev.read():
                    if event.type == ecodes.EV_KEY and event.code == BUTTON_CODE and event.value == 1:
                        now = time.time()
                        if now - last_press > 0.25:  # debounce
                            last_press = now
                            with mode_lock:
                                mode = (mode + 1) % 3
            except OSError as e:
                if e.errno != 11:  # Resource temporarily unavailable
                    print("Fehler im Input Listener:", e)


# ----------------------------
# MAIN LOOP
# ----------------------------
def main():
    global mode, colorful_mode, running
    rainbow_step = 0.0
    breath_t = 0.0
    breath_hue = 0.0
    last_breath = 0.0
    scanner_pos = 0.0
    scanner_hue = 0.0

    while running:
        with mode_lock:
            current_mode = mode

        if current_mode == 0:
            rainbow(rainbow_step)
            rainbow_step += 0.002  # Geschwindigkeit Rainbow

        elif current_mode == 1:
            breathe_outwards(breath_t, breath_hue)
            current_breath = (math.sin(breath_t) + 1) / 2
            if current_breath < 0.05 <= last_breath:
                breath_hue += 0.12  # Farbwechsel pro Zyklus
            last_breath = current_breath
            breath_t += 0.06  # Geschwindigkeit Breath

        elif current_mode == 2:
            scanner(scanner_pos, scanner_hue)
            scanner_pos += 0.3  # Geschwindigkeit Scanner
            scanner_hue += 0.002  # Farbshift

        time.sleep(0.02)


# ----------------------------
# START
# ----------------------------
if __name__ == "__main__":
    threading.Thread(target=input_listener, daemon=True).start()
    try:
        main()
    except KeyboardInterrupt:
        cleanup()
