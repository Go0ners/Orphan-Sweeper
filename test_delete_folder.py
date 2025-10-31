#!/usr/bin/env python3
from pathlib import Path
import sys
sys.path.insert(0, '.')
from orphan_sweeper import OrphanSweeper

sweeper = OrphanSweeper()
file_path = Path("test_folder/Movie.2024/Movie.2024.mkv")
sweeper.delete_file(file_path, dry_run=False)
