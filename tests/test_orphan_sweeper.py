"""
Unit tests for OrphanSweeper class
"""
import unittest
import tempfile
import os
import hashlib
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from orphan_sweeper import OrphanSweeper, FileInfo, Config


class TestOrphanSweeper(unittest.TestCase):
    """Test OrphanSweeper class"""

    def setUp(self):
        """Set up test fixtures"""
        # Create temporary directory for cache
        self.temp_dir = tempfile.mkdtemp()
        self.cache_file = Path(self.temp_dir) / "test_cache.db"
        self.sweeper = OrphanSweeper(
            cache_file=self.cache_file,
            max_workers=2,
            verbose=False,
            silent=True
        )

    def tearDown(self):
        """Clean up test fixtures"""
        # Close database connection
        if hasattr(self.sweeper, 'conn'):
            self.sweeper.conn.close()

        # Remove cache file
        if self.cache_file.exists():
            self.cache_file.unlink()

        # Remove temp directory
        if Path(self.temp_dir).exists():
            os.rmdir(self.temp_dir)

    def test_database_initialization(self):
        """Test SQLite database initialization"""
        cursor = self.sweeper.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='file_cache'"
        )
        self.assertIsNotNone(cursor.fetchone())

    def test_cache_operations(self):
        """Test cache read/write operations"""
        # Create a temporary test file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mkv') as f:
            # Write enough data (> 30MB for hash calculation)
            data = b'0' * (40 * 1024 * 1024)  # 40MB
            f.write(data)
            test_file = Path(f.name)

        try:
            # First hash should miss cache
            hash1 = self.sweeper._get_file_hash(test_file)
            self.assertIsNotNone(hash1)
            self.assertEqual(len(hash1), 32)  # MD5 hash length

            # Flush cache to ensure it's written
            self.sweeper._flush_cache()

            # Second hash should hit cache
            hash2 = self.sweeper._get_file_hash(test_file)
            self.assertEqual(hash1, hash2)

            # Verify cache entry exists
            stat = test_file.stat()
            cursor = self.sweeper.conn.execute(
                "SELECT hash FROM file_cache WHERE path=? AND mtime=? AND size=?",
                (str(test_file), stat.st_mtime, stat.st_size)
            )
            cached_hash = cursor.fetchone()
            self.assertIsNotNone(cached_hash)
            self.assertEqual(cached_hash[0], hash1)
        finally:
            # Clean up
            if test_file.exists():
                test_file.unlink()

    def test_scan_directory_filters(self):
        """Test directory scanning with filters"""
        # Create temporary directory structure
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create test files
            # Valid file (large enough)
            large_file = temp_path / "valid.mkv"
            with large_file.open('wb') as f:
                f.write(b'0' * (400 * 1024 * 1024))  # 400MB

            # Too small file (should be ignored)
            small_file = temp_path / "small.mkv"
            with small_file.open('wb') as f:
                f.write(b'0' * (100 * 1024 * 1024))  # 100MB

            # Sample file (should be ignored)
            sample_file = temp_path / "sample.mkv"
            with sample_file.open('wb') as f:
                f.write(b'0' * (400 * 1024 * 1024))  # 400MB

            # Wrong extension (should be ignored)
            wrong_ext = temp_path / "video.txt"
            with wrong_ext.open('wb') as f:
                f.write(b'0' * (400 * 1024 * 1024))  # 400MB

            # Scan directory
            files = self.sweeper._scan_directory(temp_path)

            # Should only find the large valid file
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].path.name, "valid.mkv")

    def test_report_generation(self):
        """Test report data collection"""
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "report.json"
            sweeper_with_report = OrphanSweeper(
                cache_file=self.cache_file,
                max_workers=2,
                verbose=False,
                silent=True,
                export_report=report_path
            )

            # Create a test file info
            test_file = FileInfo(
                path=Path("/test/video.mkv"),
                size=1024 * 1024 * 500,  # 500MB
                mtime=1234567890.0
            )

            # Add to report
            sweeper_with_report.add_to_report(test_file, deleted=True)

            # Export report
            sweeper_with_report.export_report_json()

            # Verify report file exists
            self.assertTrue(report_path.exists())

            # Read and verify report content
            import json
            with open(report_path, 'r') as f:
                report = json.load(f)

            self.assertEqual(len(report['files']), 1)
            self.assertEqual(report['files'][0]['name'], 'video.mkv')
            self.assertEqual(report['files'][0]['deleted'], True)
            self.assertEqual(report['orphans_deleted'], 1)

            # Clean up
            sweeper_with_report.conn.close()

    def test_dry_run_mode(self):
        """Test dry-run mode doesn't actually delete files"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create test file
            test_file = temp_path / "test.mkv"
            with test_file.open('wb') as f:
                f.write(b'test content')

            # Try to delete in dry-run mode
            result = self.sweeper.delete_file(
                test_file,
                dry_run=True,
                force_delete_folders=False,
                silent=True
            )

            # Should return True (simulated success)
            self.assertTrue(result)

            # File should still exist
            self.assertTrue(test_file.exists())


if __name__ == '__main__':
    unittest.main()
