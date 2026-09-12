#!/usr/bin/env python3
"""Compatibility entrypoint for the maintained sequential simulation harness."""

import asyncio

from tools.simulation.sequential_postflop import main


if __name__ == "__main__":
    asyncio.run(main())
