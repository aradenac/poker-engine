#!/usr/bin/env python3
"""Compatibility entry point for the repo-native Model A overlay builder."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.population_increment_overlay import main  # noqa: E402


if __name__ == "__main__":
    main()
