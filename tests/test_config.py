"""
Unit tests for Config class
"""
import unittest
import tempfile
import json
from pathlib import Path
import sys
import os

# Add parent directory to path to import orphan_sweeper
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from orphan_sweeper import Config


class TestConfig(unittest.TestCase):
    """Test Config class"""

    def test_default_values(self):
        """Test default configuration values"""
        self.assertEqual(Config.MIN_FILE_SIZE_MB, 350)
        self.assertEqual(Config.MIN_FILE_SIZE_BYTES, 350 * 1024 * 1024)
        self.assertEqual(Config.HASH_CHUNK_SIZE_MB, 10)
        self.assertEqual(Config.CACHE_BATCH_SIZE, 100)
        self.assertEqual(Config.DEFAULT_CACHE_FILE, "media_cache.db")

    def test_video_extensions(self):
        """Test video extensions set"""
        self.assertIn('.mkv', Config.VIDEO_EXTENSIONS)
        self.assertIn('.mp4', Config.VIDEO_EXTENSIONS)
        self.assertIn('.avi', Config.VIDEO_EXTENSIONS)
        self.assertEqual(len(Config.VIDEO_EXTENSIONS), 8)

    def test_ignored_keywords(self):
        """Test ignored keywords"""
        self.assertIn('sample', Config.IGNORED_KEYWORDS)

    def test_load_json_config(self):
        """Test loading configuration from JSON file"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config_data = {
                'source': '/test/source',
                'destinations': ['/test/dest1', '/test/dest2'],
                'workers': 32
            }
            json.dump(config_data, f)
            config_path = Path(f.name)

        try:
            loaded_config = Config.from_file(config_path)
            self.assertEqual(loaded_config['source'], '/test/source')
            self.assertEqual(loaded_config['workers'], 32)
            self.assertEqual(len(loaded_config['destinations']), 2)
        finally:
            config_path.unlink()

    def test_load_nonexistent_config(self):
        """Test loading from non-existent file returns empty dict"""
        config = Config.from_file(Path('/nonexistent/config.json'))
        self.assertEqual(config, {})


if __name__ == '__main__':
    unittest.main()
