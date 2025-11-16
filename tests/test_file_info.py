"""
Unit tests for FileInfo class
"""
import unittest
from pathlib import Path
from datetime import datetime
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from orphan_sweeper import FileInfo


class TestFileInfo(unittest.TestCase):
    """Test FileInfo class"""

    def test_fileinfo_creation(self):
        """Test FileInfo object creation"""
        test_path = Path('/test/video.mkv')
        test_size = 1024 * 1024 * 500  # 500MB
        test_mtime = 1234567890.0

        file_info = FileInfo(test_path, test_size, test_mtime)

        self.assertEqual(file_info.path, test_path)
        self.assertEqual(file_info.size, test_size)
        self.assertEqual(file_info.mtime, test_mtime)

    def test_mtime_str_formatting(self):
        """Test mtime string formatting"""
        test_path = Path('/test/video.mkv')
        test_size = 1024 * 1024 * 500
        test_mtime = 1234567890.0  # 2009-02-13 23:31:30

        file_info = FileInfo(test_path, test_size, test_mtime)
        mtime_str = file_info.mtime_str

        # Check format is correct
        self.assertRegex(mtime_str, r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')
        self.assertIn('2009-02-13', mtime_str)


if __name__ == '__main__':
    unittest.main()
