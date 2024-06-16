#!/usr/bin/env python3

import os
import sys

PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, PARENT_DIR)

from main import app as application
