import traceback
import dotenv
import socket
dotenv.load_dotenv()
import threading, time, json, os
from datetime import datetime
import oai_dialogue.pepper_command as pepper_command
from oai_dialogue.speech_to_text.pepper_text_speaker import PepperTextSpeaker
from oai_dialogue.speech_to_text import pcm_utils
from oai_dialogue.speech_to_text import subtitles
from oai_dialogue.speech_to_text.oaichat_integrated import OaiChatIntegrated, Query
from oai_dialogue.lesson_engine import LessonEngine
from oai_dialogue.vision_engine import VisionEngine
import oai_dialogue.comm as comm
dotenv.load_dotenv(os.getenv('DIALOGUE_ENV', 'dialogue.env'))

def main():
    command_sender = pepper_command.CommandSender()

    def init_robot():
        command_sender.send(pepper_command.ConfigSpeech(language=os.getenv('LANGUAGE', 'English'), animated=True))
        command_sender.send(pepper_command.ConfigAudio(output_volume=70))
        wifi_ssid = os.getenv('TABLET_WIFI_SSID')
        if wifi_ssid:
            print("Configuring tablet wifi:", wifi_ssid)
            command_sender.send(pepper_command.ConfigTabletWifi(
                ssid=wifi_ssid,
                pwd=os.getenv('TABLET_WIFI_PWD', ''),
                security_type=os.getenv('TABLET_WIFI_SECURITY', 'wpa')
            ))

    # Wait for robot connection with retry
    print("Waiting for robot connection...")
    connected = False
    while not connected:
        try:
            init_robot()
            connected = True
        except Exception:
            print("Robot not ready, retrying in 2 seconds...")
            time.sleep(2)
    print("Robot connected.")

    subtitle_server = subtitles.SubtitleServer()
    pts = PepperTextSpeaker(
        command_sender=command_sender,
        subtitle_server=subtitle_server
    )
    pts.push_text(os.getenv('SAY', ''))

    def on_robot_state_change(state:comm.RobotState):
        print(state)
        if state.just_started:
            init_robot()
        pts.on_robot_state_change(state)
        if state.head_touched:
            oai.cancel_current()

    robot_state_listener = comm.RobotStateListener(on_robot_state_change)

    logdir = os.path.join(os.path.dirname(__file__), 'logs')
    os.makedirs(logdir, exist_ok=True)
    logfile = os.path.join(logdir, datetime.now().strftime('dialogue_%Y-%m-%d_%H%M%S.log'))
    print('Logging to', logfile)

    def log_query(query:Query):
        entry = {
            'time': datetime.fromtimestamp(query.start_time).isoformat(),
            'user': query.query_text.strip(),
            'response': query.response_text.strip(),
            'duration': round(query.duration, 2)
        }
        with open(logfile, 'a', encoding='utf-8') as f:
            json.dump(entry, f, ensure_ascii=False)
            f.write(',\n')

    def on_query_update(query:Query):
        if query.query_text and not query.response_text:
            print("USER:", query.query_text.strip())
        if query.done:
            print(query)
            log_query(query)

    last_response_time = [0]

    def on_query_update_with_mute(query:Query):
        if query.response_text:
            last_response_time[0] = time.time()
        on_query_update(query)

    intermediate_response_text_callback = pts.push_text

    # Lesson engine setup
    lesson_normal_chat_enabled = [True]

    def speak_for_lesson(text):
        print("LESSON SPEAK:", text[:80])
        from oai_dialogue.speech_to_text.pepper_text_speaker import PepperTextSpeaker
        pts.worker = PepperTextSpeaker.Worker(pts)
        pts.worker.push_text(text)

    def set_normal_chat_for_lesson(enabled):
        lesson_normal_chat_enabled[0] = enabled

    lesson_engine = LessonEngine(speak_for_lesson, set_normal_chat_for_lesson)

    def move_for_lesson(x, y, theta):
        command_sender.send(pepper_command.Move(x=x, y=y, theta=theta))

    lesson_engine.move_callback = move_for_lesson

    base_prompt = os.getenv('PROMPT', '')
    for filename in ['courses.txt', 'staff.txt', 'events.txt']:
        filepath = os.path.join(os.path.dirname(__file__), filename)
        if os.path.isfile(filepath):
            with open(filepath, encoding='utf-8') as f:
                base_prompt += "\n\n" + f.read()

    # Vision engine setup
    vision_busy = [False]

    def speak_for_vision(text):
        print("VISION SPEAK:", text[:80])
        pts.worker = PepperTextSpeaker.Worker(pts)
        pts.worker.push_text(text)

    def set_vision_busy(busy):
        vision_busy[0] = busy

    vision_engine = VisionEngine(command_sender, speak_for_vision, set_vision_busy, system_prompt=base_prompt)

    def combined_intercept(text):
        return lesson_engine.check_trigger(text) or vision_engine.check_trigger(text)

    oai = OaiChatIntegrated(
        system_prompt=base_prompt,
        query_update_callback=on_query_update_with_mute,
        state_callback=print,
        intermediate_response_text_callback=intermediate_response_text_callback,
        lesson_intercept_callback=combined_intercept
    )
    oai.silero.threshold = .99

    control_muted = [False]

    def muter():
        while True:
            talking = robot_state_listener.state.talking
            receiving = oai.state == oai.STATE_RECEIVING_RESPONSE

            if talking or receiving:
                last_response_time[0] = time.time()

            recent_response = (time.time() - last_response_time[0]) < 3.0
            should_mute = talking or receiving or recent_response or vision_busy[0]

            if not control_muted[0]:
                oai.set_listening(not should_mute)
                subtitle_server.set_listening(not should_mute)

            time.sleep(.1)

    threading.Thread(target=muter, daemon=True).start()

    # Command server - listens for control panel commands from Windows
    def command_server():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('0.0.0.0', 7356))
        print("Control panel command server listening on port 7356")
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                cmd = data.decode('utf-8').strip()
                print(f"CONTROL: {cmd}")
                if cmd == "MUTE":
                    control_muted[0] = True
                    oai.set_listening(False)
                    subtitle_server.set_muted(True)
                    print("Pepper muted")
                elif cmd == "UNMUTE":
                    control_muted[0] = False
                    subtitle_server.set_muted(False)
                    print("Pepper unmuted")
                elif cmd.startswith("MOVE:"):
                    parts = cmd.replace("MOVE:", "").split(",")
                    x, y, theta = float(parts[0]), float(parts[1]), float(parts[2])
                    command_sender.send(pepper_command.Move(x=x, y=y, theta=theta))
                elif cmd == "STOP":
                    command_sender.send(pepper_command.Move(x=0, y=0, theta=0))
                elif cmd == "CANCEL_LESSON":
                    lesson_engine.cancel_lesson()
                elif cmd == "STATUS":
                    status = {
                        "muted": control_muted[0],
                        "lesson_active": lesson_engine.is_lesson_active(),
                        "lesson_step": lesson_engine.current_step if lesson_engine.is_lesson_active() else 0,
                        "lesson_title": lesson_engine.active_lesson.title if lesson_engine.is_lesson_active() else "None",
                        "waiting": lesson_engine.waiting_for_continue
                    }
                    sock.sendto(str(status).encode('utf-8'), addr)
            except Exception:
                traceback.print_exc()

    threading.Thread(target=command_server, daemon=True).start()
    pcm_utils.listen_on_streamed_audio([oai.push_pcm16_frames])

if __name__ == "__main__":
    main()
