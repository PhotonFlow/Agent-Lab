"""Measure HALF_W in the package copy. Stdout is one JSON object."""

import json
import re
import sys
from pathlib import Path

text = Path("pps_perception_bringup/pps_perception_bringup/synthetic_scene.py").read_text(encoding="utf-8")
match = re.search(r"^HALF_W\s*=\s*([0-9.]+)\s*$", text, re.M)
if not match:
    sys.stderr.write("HALF_W missing\n")
    sys.exit(1)
error = abs(float(match.group(1)) - 0.55)
if error < 1e-12:
    error = 0.0
json.dump({"dimension_error_m": error}, sys.stdout)
