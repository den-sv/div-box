#!/usr/bin/env python3
"""Run from a checkout on any OS: python tb.py ui"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from timebox.cli import main

main()
