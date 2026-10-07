import socket
import sys

import pygame
import time
import os
import threading

import __parentdir  # noqa: F401  (puts the repo root on sys.path)
import net_config

WSL_IP = net_config.wsl_ip()
CMD_PORT = 7356

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(0.3)

muted = False
tablet_showing_wifi = False
running = True
last_status = "Connecting..."
last_status_time = 0

def send_cmd(cmd):
    try:
        sock.sendto(cmd.encode('utf-8'), (WSL_IP, CMD_PORT))
    except Exception as e:
        pass

def poll_status():
    global last_status, last_status_time
    while running:
        try:
            sock.sendto("STATUS".encode('utf-8'), (WSL_IP, CMD_PORT))
            data, _ = sock.recvfrom(1024)
            last_status = data.decode('utf-8')
        except:
            pass
        time.sleep(2)

threading.Thread(target=poll_status, daemon=True).start()

def draw_panel(left_x, left_y, right_x):
    os.system('cls')
    mute_str = "MUTED  " if muted else "ACTIVE "
    mute_icon = "[!!]" if muted else "[OK]"
    print("=" * 55)
    print("       PEPPER CONTROL PANEL - PS5 Controller")
    print("=" * 55)
    print(f"  Microphone  : {mute_icon} {mute_str}")
    print(f"  Status      : {last_status}")
    print("=" * 55)
    print("")
    print("  Left Stick   : Walk forward / backward / strafe")
    print("  Right Stick  : Turn left / right")
    print("  Cross  (X)   : Toggle mute / unmute")
    print("  Circle (O)   : Cancel current lesson")
    print("  Square       : Wave")
    print("  Triangle     : Nod")
    print("  L1           : Point")
    print("  R1           : Bow")
    tablet_label = "subtitles" if tablet_showing_wifi else "wifi menu"
    print(f"  Share        : Tablet -> {tablet_label}")
    print("  L2           : Rock paper scissors")
    print("  R2           : Speak introduction")
    print("  Options      : Quit")
    print("")
    fwd    = -left_y
    strafe =  left_x
    turn   = -right_x
    bar_fwd    = "#" * int(abs(fwd)    * 20)
    bar_strafe = "#" * int(abs(strafe) * 20)
    bar_turn   = "#" * int(abs(turn)   * 20)
    print(f"  Forward/Back : {'FWD' if fwd > 0.1 else 'BCK' if fwd < -0.1 else '---'} |{bar_fwd:<20}| {fwd:+.2f}")
    print(f"  Strafe       : {'LFT' if strafe < -0.1 else 'RGT' if strafe > 0.1 else '---'} |{bar_strafe:<20}| {strafe:+.2f}")
    print(f"  Turn         : {'LFT' if turn > 0.1 else 'RGT' if turn < -0.1 else '---'} |{bar_turn:<20}| {turn:+.2f}")
    print("")
    print("=" * 55)

# Initialise pygame
pygame.init()
pygame.joystick.init()

if pygame.joystick.get_count() == 0:
    print("No controller detected. Plug in PS5 controller via USB and restart.")
    input("Press Enter to exit...")
    exit()

joystick = pygame.joystick.Joystick(0)
joystick.init()
print(f"Controller connected: {joystick.get_name()}")

# How the BUTTON_* indices below were established, kept runnable so the next
# one does not have to be guessed: press a button, read its number. Also
# prints axis values -- triggers like L2/R2 are often exposed as an analog
# axis (0.0 at rest, moving toward 1.0 when pressed) rather than a discrete
# button at all, which this same approach would otherwise miss entirely.
if "--discover-buttons" in sys.argv:
    print(f"{joystick.get_numbuttons()} buttons, "
          f"{joystick.get_numaxes()} axes. Press/move any; Ctrl+C to stop.")
    seen = set()
    axis_baseline = [joystick.get_axis(i) for i in range(joystick.get_numaxes())]
    try:
        while True:
            pygame.event.pump()
            pressed = {i for i in range(joystick.get_numbuttons())
                       if joystick.get_button(i)}
            for i in sorted(pressed - seen):
                print(f"  button {i} pressed")
            seen = pressed
            for i in range(joystick.get_numaxes()):
                value = joystick.get_axis(i)
                if abs(value - axis_baseline[i]) > 0.3:
                    print(f"  axis {i} moved: {value:+.2f}")
            time.sleep(0.05)
    except KeyboardInterrupt:
        pygame.quit()
        sys.exit(0)

time.sleep(1)

DEADZONE     = 0.2
MOVE_SCALE   = 0.6
TURN_SCALE   = 0.6
MOVE_INTERVAL = 0.4
DRAW_INTERVAL = 0.3  # only redraw every 300ms

# Verified on this controller by pressing each button and watching
# [joystick.get_button(i) for i in range(joystick.get_numbuttons())]:
# Cross=0, Circle=1, Options=6, Square=2, Triangle=3, L1=9, R1=10.
BUTTON_OPTIONS  = 6
BUTTON_SQUARE   = 2
BUTTON_TRIANGLE = 3
BUTTON_L1       = 9
BUTTON_R1       = 10
# Share is the one free button that was convenient; its index was NOT verified
# the same way as the others. Run `pepper_control.py --discover-buttons` and
# press Share to confirm, then correct this if it differs.
BUTTON_SHARE    = 4
# R2 is a trigger, not a discrete button -- it's almost always exposed as an
# analog AXIS (0.0 at rest, toward 1.0 fully pressed), not a get_button()
# index, unlike everything else above. AXIS_R2=5 is an unverified guess
# (SDL's common layout has L2/R2 as the last two axes, after the two
# sticks' four), not confirmed on this controller the way L1/R1/Share were.
# Run `pepper_control.py --discover-buttons` and pull R2 to confirm the
# axis number and correct it here if it differs.
AXIS_R2         = 5
# L2: same caveat as R2 -- axis 4 is the SDL-typical guess, unverified here.
# Pull L2 under --discover-buttons to confirm. The > 0.5 threshold works
# whether the trigger rests at 0.0 or -1.0.
AXIS_L2         = 4
AXIS_R2_THRESHOLD = 0.5

prev_cross    = False
prev_circle   = False
prev_options  = False
prev_square   = False
prev_triangle = False
prev_l1       = False
prev_r1       = False
prev_share    = False
prev_r2       = False
prev_l2       = False
last_move_time = 0
last_draw_time = 0
was_moving = False

while running:
    pygame.event.pump()

    left_x  = joystick.get_axis(0)
    left_y  = joystick.get_axis(1)
    right_x = joystick.get_axis(2)

    if abs(left_x)  < DEADZONE: left_x  = 0.0
    if abs(left_y)  < DEADZONE: left_y  = 0.0
    if abs(right_x) < DEADZONE: right_x = 0.0

    now = time.time()

    if now - last_move_time > MOVE_INTERVAL:
        x     = -left_y  * MOVE_SCALE
        y     = -left_x  * MOVE_SCALE
        theta = -right_x * TURN_SCALE
        is_moving = abs(x) > 0.01 or abs(y) > 0.01 or abs(theta) > 0.01
        if is_moving or was_moving:
            send_cmd(f"MOVE:{x:.3f},{y:.3f},{theta:.3f}")
        was_moving = is_moving
        last_move_time = now

    # Buttons
    cross_pressed    = joystick.get_button(0)
    circle_pressed   = joystick.get_button(1)
    options_pressed  = joystick.get_button(BUTTON_OPTIONS)
    square_pressed   = joystick.get_button(BUTTON_SQUARE)
    triangle_pressed = joystick.get_button(BUTTON_TRIANGLE)
    l1_pressed       = joystick.get_button(BUTTON_L1)
    r1_pressed       = joystick.get_button(BUTTON_R1)
    share_pressed    = joystick.get_button(BUTTON_SHARE)
    r2_pressed       = joystick.get_axis(AXIS_R2) > AXIS_R2_THRESHOLD
    l2_pressed       = joystick.get_axis(AXIS_L2) > AXIS_R2_THRESHOLD

    if cross_pressed and not prev_cross:
        muted = not muted
        send_cmd("MUTE" if muted else "UNMUTE")

    if circle_pressed and not prev_circle:
        send_cmd("CANCEL_LESSON")

    if square_pressed and not prev_square:
        send_cmd("GESTURE:wave")

    if triangle_pressed and not prev_triangle:
        send_cmd("GESTURE:nod")

    if l1_pressed and not prev_l1:
        send_cmd("GESTURE:point")

    if r1_pressed and not prev_r1:
        send_cmd("GESTURE:bow")

    if share_pressed and not prev_share:
        tablet_showing_wifi = not tablet_showing_wifi
        send_cmd("TABLET_WIFI" if tablet_showing_wifi else "TABLET_SUBTITLES")

    if r2_pressed and not prev_r2:
        send_cmd("INTRODUCTION")

    if l2_pressed and not prev_l2:
        send_cmd("RPS")

    if options_pressed and not prev_options:
        running = False
        break

    prev_cross    = cross_pressed
    prev_circle   = circle_pressed
    prev_options  = options_pressed
    prev_square   = square_pressed
    prev_triangle = triangle_pressed
    prev_l1       = l1_pressed
    prev_r1       = r1_pressed
    prev_share    = share_pressed
    prev_r2       = r2_pressed
    prev_l2       = l2_pressed

    # Only redraw every 300ms to stop flashing
    if now - last_draw_time > DRAW_INTERVAL:
        draw_panel(left_x, left_y, right_x)
        last_draw_time = now

    time.sleep(0.02)

pygame.quit()
sock.close()
print("Control panel closed.")