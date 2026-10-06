# Same trick as oai_dialogue/speech_to_text/__parentdir.py: these scripts are
# started as `py -3.13 windows_scripts\foo.py`, so sys.path[0] is this folder
# and the repo root (where net_config.py lives) is not importable. Import this
# module first to fix that.
import os
import sys
parent_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
