import os, sys
"""Make janitor scripts importable from skill directory."""
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
