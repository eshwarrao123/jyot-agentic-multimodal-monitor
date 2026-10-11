"""
Jyot Agentic Multimodal Monitor

Track B (Extended), AI Generalist Assignment for Jyot
A bounded agentic pipeline for product-safety recall monitoring.
"""

import sys

# Isolate sys.path from cross-version global site-packages (e.g. Python 3.13 site-packages in Python 3.14)
_curr_ver_str = f"Python{sys.version_info.major}{sys.version_info.minor}"
sys.path = [
    p for p in sys.path
    if not any(f"python{v[0]}{v[1]}" in p.lower() for v in [(3, 9), (3, 10), (3, 11), (3, 12), (3, 13), (3, 14), (3, 15)] if f"python{v[0]}{v[1]}" != _curr_ver_str.lower())
]

__version__ = "0.1.0"

