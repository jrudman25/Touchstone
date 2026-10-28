import sys
from pathlib import Path

# Make scripts/ importable so tests can import generate_dev_keys.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
