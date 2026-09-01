# -*- coding: utf-8 -*-
###########################################################
# Standalone spike: grab one frame from Pepper's camera via ALVideoDevice
# and save it as a real, viewable JPEG. Not wired into the app.
#
# Syntax:
#    python2 spike_camera_capture.py --pip <ip> --pport <port>
###########################################################

ROBOT_PORT = 9559
ROBOT_IP = "172.22.34.18"

from optparse import OptionParser
from naoqi import ALProxy
import vision_definitions as vd
from PIL import Image


def main():
    parser = OptionParser()
    parser.add_option("--pip", help="IP address of your robot", dest="pip")
    parser.add_option("--pport", help="port NAOqi is listening to", dest="pport", type="int")
    parser.set_defaults(pip=ROBOT_IP, pport=ROBOT_PORT)
    (opts, args_) = parser.parse_args()

    proxy = ALProxy("ALVideoDevice", opts.pip, opts.pport)

    name = None
    try:
        name = proxy.subscribeCamera("spike_capture", vd.kTopCamera, vd.kVGA, vd.kRGBColorSpace, 30)
    except (RuntimeError, AttributeError) as e:
        print("subscribeCamera failed (%s), falling back to subscribe()" % e)
        name = proxy.subscribe("spike_capture", vd.kVGA, vd.kRGBColorSpace, 30)

    try:
        image = proxy.getImageRemote(name)
        if image is None:
            print("getImageRemote returned None")
            return

        width, height, layers, colorspace = image[0], image[1], image[2], image[3]
        print("width=%s height=%s layers=%s colorspace=%s" % (width, height, layers, colorspace))
        print("array length=%s (expected %s for RGB)" % (len(image[6]), width * height * 3))

        pil_img = Image.frombytes("RGB", (width, height), bytes(bytearray(image[6])))
        out_path = "capture_test.jpg"
        pil_img.save(out_path)
        print("Saved %s" % out_path)
    finally:
        proxy.unsubscribe(name)


if __name__ == "__main__":
    main()
