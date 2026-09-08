import socket
import pygame
import time
import os
import threading

WSL_IP = "172.31.94.202"
CMD_PORT = 7356

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(0.3)

muted = False
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

prev_cross    = False
prev_circle   = False
prev_options  = False
prev_square   = False
prev_triangle = False
prev_l1       = False
prev_r1       = False
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

    # Only redraw every 300ms to stop flashing
    if now - last_draw_time > DRAW_INTERVAL:
        draw_panel(left_x, left_y, right_x)
        last_draw_time = now

    time.sleep(0.02)

pygame.quit()
sock.close()
print("Control panel closed.")