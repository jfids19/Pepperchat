# -*- coding: utf-8 -*-

###########################################################
# This module implements the main dialogue functionality for Pepper, based on ChatGPT.
#
# Syntax:
#    python scriptname --pip <ip> --pport <port>
#
#    --pip <ip>: specify the ip of your robot (without specification it will use the ROBOT_IP defined below
#
# Author: Mikael Lebram & Erik Billing, University of Skovde based on code from Johannes Bramauer, Vienna University of Technology
# Created: May 30, 2018 and updated spring progressively during in the period 2022-05 to 2024-04.
# License: MIT
###########################################################

import net_config

ROBOT_PORT = 9559
# --pip still wins; this default makes it optional once network.env has
# PEPPER_IP. Falls back to pepper.local if it does not.
ROBOT_IP = net_config.pepper_ip()

from optparse import OptionParser
import threading
import traceback
from oai_dialogue.comm import RobotStateReporter
import oai_dialogue.pepper_command as pepper_command
import naoqi
import time
import sys, os
import codecs
import io
import base64
from naoqi import ALProxy
import vision_definitions as vd
from PIL import Image

def start_thread(target):
    t = threading.Thread(target=target)
    t.setDaemon(True)
    t.start()
    return t

def encode(s):
    return codecs.encode(s,'utf-8','ignore')

# Short logical gesture names -> NaoQi ALBehaviorManager behavior IDs.
# All confirmed present via ALProxy("ALBehaviorManager", ROBOT_IP, ROBOT_PORT)
# .getInstalledBehaviors() on this robot's content pack (2026-09-08).
# wave/nod/point/bow are also bound to PS5 controller buttons (pepper_control.py);
# the rest are only reachable via the LLM-chosen gesture path (oaichat_integrated.py).
GESTURE_BEHAVIORS = {
    "wave":        "animations/Stand/Gestures/Hey_1",
    "nod":         "animations/Stand/Gestures/Yes_1",
    "point":       "animations/Stand/Gestures/Explain_5",
    "bow":         "animations/Stand/Gestures/BowShort_1",
    "no":          "animations/Stand/Gestures/No_3",
    "think":       "animations/Stand/Gestures/Thinking_4",
    "shrug":       "animations/Stand/Gestures/IDontKnow_1",
    "excited":     "animations/Stand/Gestures/Excited_1",
    "laugh":       "animations/Stand/Gestures/Laugh_1",
    "sad":         "animations/Stand/Emotions/Negative/Sad_1",
    "show_tablet": "animations/Stand/Gestures/ShowTablet_1",
}

class ModuleCommandable(naoqi.ALModule):
    def __init__(self, robot_ip, robot_port):
        naoqi.ALModule.__init__(self, mod_name)
        self.memory = ALProxy("ALMemory", robot_ip, robot_port)
        self.posture = ALProxy("ALRobotPosture", robot_ip, robot_port)
        self.autonomous_life = ALProxy('ALAutonomousLife')
        self.tts = ALProxy("ALTextToSpeech", robot_ip, robot_port)
        self.aup = ALProxy("ALAnimatedSpeech", robot_ip, robot_port)
        self.tablet = ALProxy("ALTabletService", robot_ip, robot_port)
        self.audio = ALProxy("ALAudioDevice")
        self.motion = ALProxy("ALMotion", robot_ip, robot_port)
        self.video = ALProxy("ALVideoDevice", robot_ip, robot_port)
        self.behavior_manager = ALProxy("ALBehaviorManager", robot_ip, robot_port)

        self.state_reporter = RobotStateReporter()
        self.command_receiver = pepper_command.CommandReceiver(self.on_command)
        self.memory.subscribeToEvent("TouchChanged", self.getName(), "on_touch_changed")
        self.touched = False
        self.running = True
        self.pending_speech = ""
        self.tablet_wifi_config = None
        self.speech_config = None
        self._moving = False
        self._tablet_busy = False

        def speech_loop():
            while self.running:
                try:
                    if self.pending_speech:
                        data = encode(self.pending_speech)
                        self.pending_speech = ""
                        self.state_reporter.report_talking(True)
                        if self.speech_config and self.speech_config.animated:
                            self.aup.say(data)
                        else:
                            self.tts.say(data)
                    self.state_reporter.report_talking(False)
                except:
                    traceback.print_exc()
                time.sleep(.01)
        start_thread(speech_loop)

    def connect_tablet_wifi(self):
        def wait_for_connection(timeout):
            t = time.time()
            while time.time() - t < timeout:
                if self.tablet.getWifiStatus() == "CONNECTED":
                    return True
                time.sleep(.1)
        # Reverted 2026-10-06: a version of this forced configureWifi()
        # unconditionally, on the theory that getWifiStatus()=="CONNECTED"
        # couldn't be trusted to mean "connected to the right network". That
        # theory was never actually confirmed, and forcing a full wifi
        # reconfigure/rejoin on an ALREADY-good connection turned out to be
        # the real regression: it broke a hotspot that had previously worked
        # fine, while Nescot's more robust AP infrastructure tolerated the
        # same disruption. Back to the original, safer order: trust an
        # existing connection, only reconfigure when it's actually needed.
        if wait_for_connection(3):
            return True
        if self.tablet_wifi_config:
            self.tablet.configureWifi(
                self.tablet_wifi_config.security_type.encode("utf-8"),
                self.tablet_wifi_config.ssid.encode("utf-8"),
                self.tablet_wifi_config.pwd.encode("utf-8")
            )
            if wait_for_connection(5):
                return True
        print("Tablet wifi not connected. Check credentials.")

    def capture_image(self):
        try:
            self.motion.setStiffnesses("Head", 1.0)
            self.motion.setAngles(["HeadYaw", "HeadPitch"], [0.0, -0.2], 1.0)
            time.sleep(0.5)
            name = self.video.subscribeCamera("vision_capture", vd.kTopCamera, vd.kVGA, vd.kRGBColorSpace, 30)
            try:
                image = self.video.getImageRemote(name)
                if image is None:
                    return {"error": "no image returned"}
                pil_img = Image.frombytes("RGB", (image[0], image[1]), bytes(bytearray(image[6])))
                buf = io.BytesIO()
                pil_img.save(buf, format="JPEG")
                return {"image_b64": base64.b64encode(buf.getvalue())}
            finally:
                self.video.unsubscribe(name)
        except Exception as e:
            traceback.print_exc()
            return {"error": str(e)}

    def on_command(self, command):
        try:
            if isinstance(command, pepper_command.Say):
                self.stop_talking()
                self.pending_speech = command.text

            elif isinstance(command, pepper_command.ConfigSpeech):
                if not self.speech_config or self.speech_config.animated != command.animated:
                    if command.animated:
                        self.autonomous_life.setState('solitary')
                        self.autonomous_life.stopAll()
                    else:
                        if self.autonomous_life.getState() != 'disabled':
                            self.autonomous_life.setState('disabled')
                        self.posture.goToPosture('Stand', 0.5)
                if not self.speech_config or self.speech_config.language != command.language:
                    print(command.language, self.tts.getLanguage())
                    self.tts.setLanguage(command.language.encode("utf-8"))
                self.speech_config = command

            elif isinstance(command, pepper_command.ConfigAudio):
                self.audio.setOutputVolume(command.output_volume)

            elif isinstance(command, pepper_command.Move):
                def do_move(x=command.x, y=command.y, theta=command.theta):
                    try:
                        self.motion.setStiffnesses("Body", 1.0)
                        if abs(x) < 0.01 and abs(y) < 0.01 and abs(theta) < 0.01:
                            if self._moving:
                                self._moving = False
                                self.motion.stopMove()
                                # Release head when stopped
                                self.motion.setAngles("HeadYaw", 0.0, 0.1)
                                # BasicAwareness/BackgroundMovement fight the base for the
                                # Move resource and degrade controller responsiveness - only
                                # safe to have them back once we're done driving.
                                self.autonomous_life.setAutonomousAbilityEnabled("BasicAwareness", True)
                                self.autonomous_life.setAutonomousAbilityEnabled("BackgroundMovement", True)
                        else:
                            # Continuously lock head every move command to override tracking
                            self.motion.setAngles("HeadYaw", 0.0, 1.0)
                            self.motion.setAngles("HeadPitch", 0.0, 1.0)
                            if not self._moving:
                                self._moving = True
                                self.autonomous_life.setAutonomousAbilityEnabled("BasicAwareness", False)
                                self.autonomous_life.setAutonomousAbilityEnabled("BackgroundMovement", False)
                            self.motion.moveToward(x, y, theta)
                    except:
                        traceback.print_exc()
                start_thread(do_move)

            elif isinstance(command, pepper_command.PlayGesture):
                if self._moving:
                    print("Ignoring gesture '%s': currently driving" % command.name)
                else:
                    behavior_id = GESTURE_BEHAVIORS.get(command.name)
                    if behavior_id is None:
                        print("Unknown gesture requested: %s" % command.name)
                    else:
                        def do_gesture(behavior_id=behavior_id):
                            try:
                                self.behavior_manager.runBehavior(behavior_id)
                            except:
                                traceback.print_exc()
                        start_thread(do_gesture)

            elif isinstance(command, pepper_command.ConfigTabletWifi):
                self.tablet_wifi_config = command

            elif isinstance(command, pepper_command.OpenUrlOnTablet):
                def connect_and_open():
                    if self.connect_tablet_wifi():
                        self.tablet.loadUrl(command.url.encode("utf-8"))
                        self.tablet.showWebview()
                start_thread(connect_and_open)

            elif isinstance(command, pepper_command.ShowTabletUrl):
                # Pepper has TWO separate wifi connections: the robot head's
                # (NaoQi/--pip) and the tablet's own Android wifi, joined
                # separately via ConfigTabletWifi/configureWifi. The internal
                # settings page (net_config.robot_settings_url(), the
                # command.url=None case) is reached over the tablet<->head
                # link and needs neither to be on any wifi at all -- which is
                # why it has worked throughout this whole investigation
                # regardless of every other fix tried. Any OTHER url
                # (currently just the subtitle page) genuinely needs the
                # TABLET's own wifi to be joined to the current network, and
                # nothing in this codebase was actually verifying or
                # re-establishing that for a NEW network -- the original
                # connect_tablet_wifi() gate only ever ran once, at dispatcher
                # startup, using whatever wifi the tablet happened to have at
                # that moment.
                if self._tablet_busy:
                    # The wifi-(re)join step below can take up to 6s, long
                    # enough for an impatient second button press to fire a
                    # whole second show_url() thread before the first one
                    # finishes -- confirmed in testing (2026-10-06): two
                    # overlapping threads both called hideWebview/loadUrl/
                    # showWebview on the tablet, and whichever happened to
                    # call showWebview() last silently won, regardless of
                    # which command was logically the most recent. Drop the
                    # new one rather than queue it -- a dropped repeat of the
                    # same toggle is harmless, same spirit as _moving above.
                    print("Tablet busy with a previous ShowTabletUrl -- "
                          "dropping this one.")
                    return
                self._tablet_busy = True

                def show_url():
                    url = command.url or net_config.robot_settings_url()
                    try:
                        if command.url:
                            status = self.tablet.getWifiStatus()
                            print("Tablet wifi status:", status)
                            # Reverted 2026-10-06: this used to force
                            # configureWifi() unconditionally even when
                            # already CONNECTED, on an unconfirmed theory
                            # that status couldn't be trusted. That forced
                            # reconfigure turned out to be the actual
                            # regression -- it broke a hotspot connection
                            # that had previously worked fine by repeatedly
                            # disrupting an already-good link, something
                            # Nescot's more robust AP infrastructure happened
                            # to tolerate but this hotspot didn't. Back to
                            # only reconfiguring when genuinely needed.
                            if status != "CONNECTED" and self.tablet_wifi_config:
                                print("Tablet wifi not connected -- "
                                      "rejoining with the stored "
                                      "credentials (ssid=%s)"
                                      % self.tablet_wifi_config.ssid)
                                self.tablet.configureWifi(
                                    self.tablet_wifi_config.security_type.encode("utf-8"),
                                    self.tablet_wifi_config.ssid.encode("utf-8"),
                                    self.tablet_wifi_config.pwd.encode("utf-8")
                                )
                                t0 = time.time()
                                while time.time() - t0 < 6:
                                    status = self.tablet.getWifiStatus()
                                    if status == "CONNECTED":
                                        break
                                    time.sleep(.3)
                                print("Tablet wifi status after rejoin attempt:", status)
                            elif status != "CONNECTED":
                                print("Tablet wifi not connected, and no "
                                      "ConfigTabletWifi credentials have "
                                      "been received -- check "
                                      "TABLET_WIFI_SSID/PWD in .env.")

                        # These NAOqi calls return immediately without
                        # waiting for the underlying Android-side work (tear
                        # down, navigate, fetch, render) to finish, so firing
                        # them back-to-back races the tablet's own pipeline.
                        # Confirmed by two observed failure modes in testing:
                        # with no hideWebview() at all, showWebview() alone
                        # was a no-op on an already-visible webview (stuck on
                        # the old page); with hideWebview() but no pause,
                        # showWebview() revealed the webview before loadUrl()
                        # had anything to paint (blank white). Hide, pause,
                        # load, pause for the fetch/render to start, then
                        # show — so there's always real content by the time
                        # it's revealed.
                        self.tablet.hideWebview()
                        time.sleep(0.3)
                        self.tablet.loadUrl(url.encode("utf-8"))
                        time.sleep(1.0)
                        self.tablet.showWebview()
                        print("Loaded on tablet:", url)
                    except Exception:
                        print("FAILED to load on tablet:", url)
                        traceback.print_exc()
                    finally:
                        self._tablet_busy = False
                start_thread(show_url)

            elif isinstance(command, pepper_command.CaptureImage):
                return self.capture_image()

        except Exception as e:
            traceback.print_exc()
            return {"error": str(e)}

    def on_touch_changed(self, name, touches):
        touched = any([len(touch) > 1 and touch[1] == True for touch in touches])
        self.state_reporter.report_head_touched(touched)
        if touched:
            self.stop_talking()
            self.pending_speech = ""
            try:
                self.tts.stopAll()
                self.aup.stopAll()
            except:
                pass

    def __del__(self):
        self.stop()

    def stop(self):
        self.memory.unsubscribe(self.getName())
        self.running = False
        self.stop_talking()

    def version(self):
        return "1.0"

    def stop_talking(self):
        self.pending_speech = ""
        self.tts.stopAll()
        self.state_reporter.report_talking(False)

def main():
    parser = OptionParser()
    parser.add_option("--pip",
        help="Parent broker port. The IP address or your robot",
        dest="pip")
    parser.add_option("--pport",
        help="Parent broker port. The port NAOqi is listening to",
        dest="pport",
        type="int")
    parser.set_defaults(
        pip=ROBOT_IP,
        pport=ROBOT_PORT)

    (opts, args_) = parser.parse_args()
    pip   = opts.pip
    pport = opts.pport

    myBroker = naoqi.ALBroker("myBroker",
       "0.0.0.0",
       0,
       pip,
       pport)

    global mod_name
    mod_name = "modcomm"
    global modcomm
    modcomm = ModuleCommandable(pip, pport)

    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        pass
    myBroker.shutdown()

if __name__ == "__main__":
    main()
