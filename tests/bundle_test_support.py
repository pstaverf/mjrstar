"""Use the one canonical backend source, including fresh app globals per fixture."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import server

load_application = server.load_application
