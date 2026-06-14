"""
server/services/scorer.py

Re-exports Scorer from src/scorer/scorer.py so the server
doesn't duplicate the scoring logic.
"""

import sys
from pathlib import Path

# Add src/scorer to path so we can import scorer.py directly
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src" / "scorer"))

from scorer_engine import Scorer

__all__ = ["Scorer"]