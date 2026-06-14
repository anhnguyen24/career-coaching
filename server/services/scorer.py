"""
server/services/scorer.py
Imports Scorer directly from the copied scorer_engine.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from scorer_engine import Scorer  # noqa: F401

__all__ = ["Scorer"]