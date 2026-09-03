import pyaudio
import socket
import struct
import threading

SAMPLE_RATE = 48000
CHANNELS = 1
CHUNK = 4096
WSL_IP = "172.31.94.202"
UDP_PORT = 50005
CONTROL_PORT = 7357

p = pyaudio.PyAudio()

stream = p.open(
    format=pyaudio.paInt16,
    channels=CHANNELS,
    rate=SAMPLE_RATE,
    input=True,
    frames_per_buffer=CHUNK,
    input_device_index=4  # Microphone Array (AMD Audio Device) — this laptop's built-in mic.
    # This index isn't stable: plugging in a new audio device (e.g. the PS5
    # DualSense controller's built-in headset mic) inserts entries ahead of
    # it and shifts the number. Re-check with pyaudio.PyAudio().get_device_info_by_index()
    # over range(get_device_count()) if the mic stops picking anything up.
)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Control socket — listens for MUTE/UNMUTE from WSL
ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
ctrl_sock.bind(('0.0.0.0', CONTROL_PORT))
ctrl_sock.settimeout(0.1)

muted = False

def control_listener():
    global muted
    while True:
        try:
            data, _ = ctrl_sock.recvfrom(64)
            cmd = data.decode('utf-8').strip()
            if cmd == "MUTE":
                muted = True
            elif cmd == "UNMUTE":
                muted = False
        except:
            pass

threading.Thread(target=control_listener, daemon=True).start()

print("Streaming mic to {}:{}".format(WSL_IP, UDP_PORT))
print("Mute control listening on port {}".format(CONTROL_PORT))

idx = 0
while True:
    try:
        data = stream.read(CHUNK, exception_on_overflow=False)
        if not muted:
            header = struct.pack('!IIII', idx & 0xFFFFFFFF, SAMPLE_RATE, CHANNELS, len(data))
            sock.sendto(header + data, (WSL_IP, UDP_PORT))
            idx += 1
    except KeyboardInterrupt:
        break

stream.stop_stream()
stream.close()
p.terminate()
sock.close()
ctrl_sock.close()