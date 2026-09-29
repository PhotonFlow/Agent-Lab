import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import algo

json.dump({"latency_ms": getattr(algo, "LATENCY_MS", 10), "score": algo.VALUE}, sys.stdout)
