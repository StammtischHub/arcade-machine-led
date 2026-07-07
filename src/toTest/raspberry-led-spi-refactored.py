import time
import math
import colorsys
import threading
import signal
import sys

from apa102_pi.driver import apa102
from evdev import InputDevice, ecodes, categorize

# ----------------------------
# CONFIG
# ----------------------------
NUM_LEDS = 65
HOLD_THRESHOLD = 2.0        # Sekunden für langen Druck (Moduswechsel)
DEBOUNCE_TIME = 0.25        # Sekunden Entprellung

device = InputDevice("/dev/input/event0")
led_button = ecodes.BTN_TOP2
strip = apa102.APA102(num_led=NUM_LEDS)

# Mode 0 = Colorful (3 Subtypen), 1 = Static (6 Subtypen), 2 = Off
mode = 0
current_mode_type = 0
mode_lock = threading.Lock()

static_colors = [
    (255, 0, 0),
    (255, 255, 0),
    (0, 255, 0),
    (0, 255, 255),
    (0, 0, 255),
    (255, 0, 255),
]

running = True


# ----------------------------
# CLEANUP
# ----------------------------
def cleanup(signum=None, frame=None):
    global running
    print("Service stopping, turning off LEDs...")
    running = False
    strip.clear_strip()
    strip.show()
    sys.exit(0)


signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT, cleanup)


# ----------------------------
# HELPER
# ----------------------------
def hsv_to_rgb(h, s=1.0, v=1.0):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return int(r * 255), int(g * 255), int(b * 255)


def cycle_mode_type():
    global mode, current_mode_type
    subtypes = {0: 3, 1: 6, 2: 1}
    with mode_lock:
        current_mode_type = (current_mode_type + 1) % subtypes.get(mode, 1)


def advance_mode():
    global mode, current_mode_type
    with mode_lock:
        mode = (mode + 1) % 3
        current_mode_type = 0


# ----------------------------
# EFFECTS
# ----------------------------
def breathe(breathe_time, base_hue):
    center = (NUM_LEDS - 1) / 2
    breath = (math.sin(breathe_time) + 1) / 2
    base_r, base_g, base_b = hsv_to_rgb(base_hue)
    for pixel in range(NUM_LEDS):
        dist = abs(pixel - center)
        falloff = max(0.0, 1.0 - (dist / center))
        brightness = breath * falloff
        target_color = int(base_r * brightness), int(base_g * brightness), int(base_b * brightness)
        strip.set_pixel(pixel, *target_color)
    strip.show()


def scanner(position, hue):
    strip.clear_strip()
    main_r, main_g, main_b = hsv_to_rgb(hue)
    pos = int(position) % NUM_LEDS - 3
    strip.set_pixel(pos, main_r, main_g, main_b)
    for offset in range(1, 6):
        fade = max(0.0, 1.0 - (offset / 6))
        target_color = int(main_r * fade), int(main_g * fade), int(main_b * fade)
        if pos - offset >= 0:
            strip.set_pixel(pos - offset, *target_color)
        if pos + offset < NUM_LEDS:
            strip.set_pixel(pos + offset, *target_color)
    strip.show()


def epilepsy(hue):
    target_color = hsv_to_rgb(hue)
    for pixel in range(NUM_LEDS):
        strip.set_pixel(pixel, *target_color)
    strip.show()


# ----------------------------
# INPUT THREAD
# ----------------------------
def input_listener():
    """
    Kurzer Druck  → Subtyp wechseln
    2s gedrückt halten → Hauptmodus wechseln (sofort beim Erreichen der Schwelle,
                         nicht erst beim Loslassen)
    """
    last_press = 0.0
    last_release = 0.0
    hold_triggered = False      # Verhindert Doppelauslösung nach langem Druck
    hold_timer: threading.Timer | None = None

    def on_hold():
        nonlocal hold_triggered
        hold_triggered = True
        advance_mode()

    try:
        for event in device.read_loop():
            if event.type != ecodes.EV_KEY or event.code != led_button:
                continue

            key_event = categorize(event)
            now = time.time()

            if key_event.keystate == key_event.key_down:
                if now - last_press < DEBOUNCE_TIME:
                    continue
                last_press = now
                hold_triggered = False

                hold_timer = threading.Timer(HOLD_THRESHOLD, on_hold)
                hold_timer.start()

            elif key_event.keystate == key_event.key_up:
                if now - last_release < DEBOUNCE_TIME:
                    continue
                last_release = now

                if hold_timer is not None:
                    hold_timer.cancel()
                    hold_timer = None

                if not hold_triggered:
                    cycle_mode_type()

    except OSError as e:
        if e.errno != 11:   # 11 = EAGAIN / Resource temporarily unavailable
            print(f"Fehler im Input Listener: {e}")


# ----------------------------
# MAIN LOOP
# ----------------------------
def main():
    global running

    breath_t = 0.0
    breath_hue = 0.0
    last_breath = 0.0

    scanner_pos = 0.0
    scanner_hue = 0.0
    scanner_direction = 1   # 1 = vorwärts, -1 = rückwärts

    epilepsy_hue = 0.0

    current_static_color = None     # None zwingt beim ersten Durchlauf zur Aktualisierung

    while running:
        with mode_lock:
            current_mode = mode
            current_type = current_mode_type

        # --- Colorful ---
        if current_mode == 0:
            if current_type == 0:
                breathe(breath_t, breath_hue)
                current_breath = (math.sin(breath_t) + 1) / 2
                if current_breath < 0.05 <= last_breath:
                    breath_hue += 0.12      # Farbwechsel pro Zyklus
                last_breath = current_breath
                breath_t += 0.04            # Geschwindigkeit Breath

            elif current_type == 1:
                scanner(scanner_pos, scanner_hue)
                if scanner_pos >= NUM_LEDS - 1:
                    scanner_direction = -1
                elif scanner_pos <= 0:
                    scanner_direction = 1
                scanner_pos += 0.35 * scanner_direction  # Geschwindigkeit Scanner
                scanner_hue += 0.002                     # Farbshift

            elif current_type == 2:
                epilepsy(epilepsy_hue)
                epilepsy_hue += 0.12

        # --- Static ---
        elif current_mode == 1:
            target_color = static_colors[current_type]
            if current_static_color != target_color:
                strip.clear_strip()
                for pixel in range(NUM_LEDS):
                    strip.set_pixel(pixel, *target_color)
                strip.show()
                current_static_color = target_color

        # --- Off ---
        elif current_mode == 2:
            if current_static_color != (0, 0, 0):
                strip.clear_strip()
                strip.show()
                current_static_color = (0, 0, 0)

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
