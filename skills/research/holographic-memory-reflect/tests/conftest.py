import os
"""Make reflect_pipeline importable from skill directory."""
import sys, os
skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, skill_dir)
