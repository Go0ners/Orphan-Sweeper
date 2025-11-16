#!/usr/bin/env python3
"""
Orphan File Sweeper - Deletes orphan video files without match.
"""
import hashlib
import json
import logging
import sqlite3
import sys
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from threading import Lock
from time import time
from typing import List, Optional, Set, Dict, Tuple, TypedDict
from queue import Queue
import os
import shutil
import select

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class CacheEntry(TypedDict):
    """Type definition for cache entries."""
    path: str
    mtime: float
    size: int
    hash: str


class Config:
    """Configuration constants for Orphan Sweeper."""

    # File size limits
    MIN_FILE_SIZE_MB: int = 350
    MIN_FILE_SIZE_BYTES: int = MIN_FILE_SIZE_MB * 1024 * 1024

    # Hash calculation
    HASH_CHUNK_SIZE_MB: int = 10
    HASH_CHUNK_SIZE_BYTES: int = HASH_CHUNK_SIZE_MB * 1024 * 1024

    # Cache settings
    CACHE_BATCH_SIZE: int = 100
    DEFAULT_CACHE_FILE: str = "media_cache.db"

    # Video file extensions
    VIDEO_EXTENSIONS: Set[str] = {
        '.mkv', '.mp4', '.avi', '.mov', '.wmv',
        '.flv', '.webm', '.m4v'
    }

    # Ignored patterns
    IGNORED_KEYWORDS: Set[str] = {'sample'}

    # Performance
    FILE_READ_BUFFER_SIZE: int = 1024 * 1024  # 1MB buffer

    # UI
    PAUSE_TIMEOUT_SECONDS: int = 10

    @classmethod
    def from_file(cls, config_path: Path) -> Dict:
        """Load configuration from JSON/YAML file."""
        if not config_path.exists():
            return {}

        try:
            with open(config_path, 'r') as f:
                if config_path.suffix in {'.yml', '.yaml'}:
                    try:
                        import yaml
                        return yaml.safe_load(f)
                    except ImportError:
                        logger.warning("PyYAML not installed, skipping YAML config")
                        return {}
                elif config_path.suffix == '.json':
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load config from {config_path}: {e}")

        return {}


class FileInfo:
    """Video file information."""
    
    def __init__(self, path: Path, size: int, mtime: float) -> None:
        self.path = path
        self.size = size
        self.mtime = mtime
    
    @property
    def mtime_str(self) -> str:
        return datetime.fromtimestamp(self.mtime).strftime('%Y-%m-%d %H:%M:%S')


class OrphanSweeper:
    """Orphan video file detector and remover."""

    def __init__(
        self,
        cache_file: Path = Path(Config.DEFAULT_CACHE_FILE),
        max_workers: int = 4,
        verbose: bool = False,
        silent: bool = False,
        export_report: Optional[Path] = None
    ) -> None:
        self.cache_file = cache_file
        self.conn = self._init_db()
        self.max_workers = max_workers
        self.db_lock = Lock()
        self.pending_commits: List[Tuple[str, float, int, str]] = []
        self.verbose = verbose
        self.silent = silent
        self.log_queue: Queue = Queue()
        self.export_report = export_report
        self.report_data: Dict = {
            'scan_date': datetime.now().isoformat(),
            'source': None,
            'destinations': [],
            'orphans_detected': 0,
            'orphans_deleted': 0,
            'total_size_bytes': 0,
            'total_size_freed_bytes': 0,
            'scan_duration_seconds': 0,
            'files': []
        }
    
    def __del__(self) -> None:
        """Close SQLite connection."""
        if hasattr(self, 'conn'):
            self.conn.close()
    
    def _init_db(self) -> sqlite3.Connection:
        """Initialize SQLite database."""
        conn = sqlite3.connect(str(self.cache_file), check_same_thread=False)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS file_cache (
                path TEXT NOT NULL,
                mtime REAL NOT NULL,
                size INTEGER NOT NULL,
                hash TEXT NOT NULL,
                PRIMARY KEY (path, mtime, size)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_hash ON file_cache(hash)")
        conn.commit()
        return conn
    
    def clear_cache(self) -> None:
        """Clear cache."""
        self.conn.execute("DELETE FROM file_cache")
        self.conn.commit()
        logger.info(f"\n✅ Cache cleared: {self.cache_file}")
    
    def display_cache(self) -> None:
        """Display cache statistics."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM file_cache")
        total = cursor.fetchone()[0]
        
        cursor = self.conn.execute("SELECT SUM(size) FROM file_cache")
        total_size = cursor.fetchone()[0] or 0
        
        print("\n" + "="*60)
        print("📊 CACHE STATISTICS")
        print("="*60)
        logger.info(f"📁 Cache file: {self.cache_file}")
        logger.info(f"📊 Total entries: {total:,}")
        logger.info(f"💾 Total size tracked: {total_size / (1024**3):.2f} GB")
        
        if total > 0:
            cursor = self.conn.execute(
                "SELECT path, datetime(mtime, 'unixepoch'), size, hash FROM file_cache ORDER BY mtime DESC LIMIT 5"
            )
            print("\n📋 Latest 5 entries:")
            for row in cursor:
                print(f"  • {row[0]}")
                print(f"    Date: {row[1]} | Size: {row[2] / (1024**2):.2f} MB | Hash: {row[3][:16]}...")
        
        print("="*60 + "\n")
    
    def _get_file_hash(self, file_path: Path) -> Optional[str]:
        """Calculate MD5 hash with cache (partial hash for large files)."""
        try:
            stat = file_path.stat()
        except OSError:
            return None
        
        path_str = str(file_path)
        file_size = stat.st_size
        
        # Check cache (thread-safe read)
        with self.db_lock:
            cursor = self.conn.execute(
                "SELECT hash FROM file_cache WHERE path=? AND mtime=? AND size=?",
                (path_str, stat.st_mtime, stat.st_size)
            )
            row = cursor.fetchone()
            if row:
                if self.verbose:
                    self.log_queue.put(f"✅ Cache hit: {file_path.name}")
                return row[0]
        
        try:
            if self.verbose:
                self.log_queue.put(f"🔐 Calculating hash: {file_path.name}")

            hasher = hashlib.md5()
            chunk_size = Config.HASH_CHUNK_SIZE_BYTES

            with file_path.open('rb') as f:
                hasher.update(f.read(chunk_size))
                f.seek(file_size // 2 - chunk_size // 2)
                hasher.update(f.read(chunk_size))
                f.seek(max(0, file_size - chunk_size))
                hasher.update(f.read(chunk_size))

            file_hash = hasher.hexdigest()

            # Add to batch (thread-safe write)
            with self.db_lock:
                self.pending_commits.append((path_str, stat.st_mtime, stat.st_size, file_hash))
                if len(self.pending_commits) >= Config.CACHE_BATCH_SIZE:
                    self.conn.executemany(
                        "INSERT OR REPLACE INTO file_cache (path, mtime, size, hash) VALUES (?, ?, ?, ?)",
                        self.pending_commits
                    )
                    self.conn.commit()
                    self.pending_commits.clear()
            
            return file_hash
            
        except (OSError, IOError):
            return None
    
    def _flush_cache(self) -> None:
        """Commit all pending hashes."""
        with self.db_lock:
            if self.pending_commits:
                self.conn.executemany(
                    "INSERT OR REPLACE INTO file_cache (path, mtime, size, hash) VALUES (?, ?, ?, ?)",
                    self.pending_commits
                )
                self.conn.commit()
                self.pending_commits.clear()
    
    def _scan_directory(self, directory: Path) -> List[FileInfo]:
        """Scan directory and return video file info."""
        if not directory.exists():
            if not self.silent:
                logger.error(f"❌ Directory does not exist: {directory}")
            return []
        
        if not self.silent:
            logger.info(f"📁 Scan: {directory}")
        files_info: List[FileInfo] = []
        
        for file_path in directory.rglob("*"):
            if not (file_path.is_file() and
                   file_path.suffix.lower() in Config.VIDEO_EXTENSIONS):
                continue

            try:
                stat = file_path.stat()
                # Ignore files below minimum size
                if stat.st_size < Config.MIN_FILE_SIZE_BYTES:
                    continue
                # Ignore files with ignored keywords in name
                if any(keyword in file_path.name.lower() for keyword in Config.IGNORED_KEYWORDS):
                    continue
                
                files_info.append(FileInfo(
                    path=file_path,
                    size=stat.st_size,
                    mtime=stat.st_mtime
                ))
            
            except OSError:
                pass
        
        return files_info
    
    def find_orphans(self, source_dir: Path, dest_dirs: List[Path]) -> List[FileInfo]:
        """Find orphan files in source directory."""
        if not self.silent:
            logger.info("\n" + "="*60)
            logger.info("🔍 FILE ANALYSIS")
            logger.info("="*60)
        
        # Detect common subdirectories between source and destinations
        source_subdirs = {d.name for d in source_dir.iterdir() if d.is_dir()}
        matched_pairs = []
        
        for dest_dir in dest_dirs:
            dest_subdirs = {d.name for d in dest_dir.iterdir() if d.is_dir()}
            common = source_subdirs & dest_subdirs
            
            if common:
                if not self.silent:
                    logger.info(f"\n🔗 Matched subdirs with {dest_dir.name}: {', '.join(sorted(common))}")
                for subdir in common:
                    matched_pairs.append((source_dir / subdir, dest_dir / subdir))
        
        # If no match, compare root directories directly
        if not matched_pairs:
            if not self.silent:
                logger.info("\n⚠️  No common subdirs, direct comparison")
            matched_pairs = [(source_dir, dest_dir) for dest_dir in dest_dirs]
        
        # Scan source (all matched subdirectories)
        source_files = []
        for src, _ in matched_pairs:
            if src == source_dir:
                source_files.extend(self._scan_directory(source_dir))
                break
        else:
            scanned_sources = set()
            for src, _ in matched_pairs:
                if src not in scanned_sources:
                    source_files.extend(self._scan_directory(src))
                    scanned_sources.add(src)
        
        if not self.silent:
            logger.info(f"   Source: {len(source_files)} files")
        
        dest_files: List[FileInfo] = []
        scanned_dests = set()
        for _, dest in matched_pairs:
            if dest not in scanned_dests:
                dest_info = self._scan_directory(dest)
                dest_files.extend(dest_info)
                if not self.silent:
                    logger.info(f"   Destination: {len(dest_info)} files")
                scanned_dests.add(dest)
        
        if not self.silent:
            logger.info(f"\n📊 Total destinations: {len(dest_files)} files")
        
        dest_metadata = {(f.size, f.mtime) for f in dest_files}
        candidates = [
            f for f in source_files 
            if (f.size, f.mtime) not in dest_metadata
        ]
        
        if not self.silent:
            logger.info(f"⚡ Fast filter: {len(candidates)} orphan candidates")
        
        if not candidates:
            return []
        
        if not self.silent:
            print(f"\n🔐 Calculating hash for {len(candidates)} candidates...")
        candidate_hashes = self._compute_hashes_parallel(candidates)
        
        candidate_sizes = {f.size for f in candidates}
        dest_to_hash = [f for f in dest_files if f.size in candidate_sizes]
        
        if not self.silent:
            print(f"\n🔐 Calculating hash for {len(dest_to_hash)} destinations...")
        dest_hash_map = self._compute_hashes_parallel(dest_to_hash)
        dest_hashes = set(dest_hash_map.keys())
        
        self._flush_cache()
        
        orphans = [
            file_info for file_hash, file_info in candidate_hashes.items()
            if file_hash not in dest_hashes
        ]
        
        if orphans and not self.silent:
            print(f"\n⏸️  {len(orphans)} orphan(s) detected. Press Enter to continue (auto in {Config.PAUSE_TIMEOUT_SECONDS}s)...")
            if sys.stdin.isatty():
                ready, _, _ = select.select([sys.stdin], [], [], Config.PAUSE_TIMEOUT_SECONDS)
                if ready:
                    sys.stdin.readline()
            else:
                time.sleep(Config.PAUSE_TIMEOUT_SECONDS)
        
        return orphans
    
    def confirm_deletion(self, file_info: FileInfo, auto_delete: bool = False, dry_run: bool = False, silent: bool = False) -> tuple[bool, bool]:
        """Ask confirmation to delete a file. Returns (delete, yes_to_all)."""
        if silent:
            print(f"\n🗑️  {file_info.path.name}")
        else:
            print(f"\n{'─'*60}")
            print("🗑️  ORPHAN FILE DETECTED")
            print(f"{'─'*60}")
            print(f"📄 File: {file_info.path.name}")
            print(f"📂 Path: {file_info.path.parent}")
            print(f"💾 Size: {file_info.size:,} bytes ({file_info.size / (1024**2):.2f} MB)")
            print(f"📅 Date: {file_info.mtime_str}")
            print("\n⚠️  This file does not exist in any destination.")
        
        if dry_run:
            if not silent:
                print("\n🔍 [DRY-RUN] Would be deleted")
            return (True, False)
        
        if auto_delete:
            if not silent:
                print("\n⚡ Automatic deletion enabled")
            return (True, False)
        
        while True:
            choice = input("\n❓ Delete this file? ([Y]es/n/a/q): ").lower().strip()
            if choice in ('', 'y', 'yes'):
                return (True, False)
            elif choice in ('n', 'no'):
                return (False, False)
            elif choice in ('a', 'all'):
                print("\n⚡ Deleting all remaining files")
                return (True, True)
            elif choice == 'q':
                print("\n👋 Operation aborted")
                sys.exit(0)
            print("⚠️  Invalid answer. Use: y (yes) / n (no) / a (all) / q (quit)")
    
    def _compute_hashes_parallel(self, files: List[FileInfo]) -> dict[str, FileInfo]:
        """Calculate hashes in parallel with progress."""
        result = {}
        total = len(files)
        completed = 0
        start_time = time()
        executor = ThreadPoolExecutor(max_workers=self.max_workers)
        
        # Get terminal height for verbose mode
        term_height = shutil.get_terminal_size().lines if self.verbose else 0
        
        try:
            futures = {executor.submit(self._get_file_hash, f.path): f for f in files}
            
            for future in as_completed(futures):
                file_info = futures[future]
                completed += 1
                
                try:
                    file_hash = future.result()
                    if file_hash:
                        result[file_hash] = file_info
                except Exception:
                    pass
                
                # Calculate progress
                elapsed = time() - start_time
                percent = (completed / total) * 100
                rate = completed / elapsed if elapsed > 0 else 0
                eta_seconds = (total - completed) / rate if rate > 0 else 0
                
                eta_str = f"{eta_seconds:.0f}s" if eta_seconds < 60 else f"{eta_seconds/60:.0f}min" if eta_seconds < 3600 else f"{eta_seconds/3600:.1f}h"
                
                progress_line = f"   ⏳ Progress: {completed}/{total} ({percent:.1f}%) | ⚡ {rate:.1f} files/s | 💻 {self.max_workers}/{os.cpu_count() or 1} threads | ⏱️  ETA: {eta_str}"
                
                if self.verbose:
                    logs = []
                    while not self.log_queue.empty():
                        logs.append(self.log_queue.get())
                    
                    if logs:
                        if term_height > 0:
                            sys.stdout.write(f"\033[{term_height};0H\033[K")
                        for log_msg in logs:
                            print(log_msg)
                    
                    if term_height > 0:
                        sys.stdout.write(f"\033[s\033[{term_height};0H\033[K{progress_line}\033[u")
                    else:
                        sys.stdout.write(f"\r{progress_line}")
                else:
                    sys.stdout.write(f"\r{progress_line}")
                
                sys.stdout.flush()
            
            executor.shutdown(wait=True)
        except KeyboardInterrupt:
            if self.verbose and term_height > 0:
                sys.stdout.write(f"\033[{term_height};0H\033[K\n")
            else:
                sys.stdout.write("\n")
            sys.stdout.flush()
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        
        if self.verbose and term_height > 0:
            sys.stdout.write(f"\033[{term_height};0H\033[K\n")
        elif not self.silent:
            sys.stdout.write("\n")
        
        if not self.silent:
            sys.stdout.flush()
        return result
    
    def delete_file(self, file_path: Path, dry_run: bool = False, force_delete_folders: bool = False, silent: bool = False) -> bool:
        """Delete file and parent folder if name matches."""
        parent_dir = file_path.parent
        should_delete_parent = parent_dir.name == file_path.stem
        
        if dry_run:
            if not silent:
                logger.info(f"   🔍 [DRY-RUN] {file_path.name}")
                if should_delete_parent:
                    logger.info(f"   🔍 [DRY-RUN] Folder: {parent_dir.name}/")
            return True
        
        try:
            file_path.unlink()
            if silent:
                logger.info(f"   ✅ {file_path.name}")
            else:
                logger.info(f"   ✅ Deleted: {file_path.name}")
            
            if should_delete_parent:
                try:
                    remaining_files = list(parent_dir.iterdir())
                    if not remaining_files:
                        parent_dir.rmdir()
                        if not silent:
                            logger.info(f"   ✅ Folder deleted: {parent_dir.name}/")
                    else:
                        if not silent:
                            logger.info(f"   ⚠️  Folder not empty: {parent_dir.name}/")
                            logger.info(f"   📋 Remaining files ({len(remaining_files)}):")
                            for f in remaining_files:
                                logger.info(f"      • {f.name} ({f.suffix or 'no extension'})")
                        
                        if not dry_run:
                            if force_delete_folders:
                                if not silent:
                                    logger.info("   ⚡ Auto-deleting folder (--force-delete-folders enabled)")
                                choice = 'y'
                            else:
                                choice = input("\n   ❓ Delete remaining files and folder? (y/N): ").lower().strip()
                            
                            if choice in ('y', 'yes'):
                                for f in remaining_files:
                                    try:
                                        if f.is_file():
                                            f.unlink()
                                            if not silent:
                                                logger.info(f"      ✅ Deleted: {f.name}")
                                        elif f.is_dir():
                                            shutil.rmtree(f)
                                            if not silent:
                                                logger.info(f"      ✅ Deleted folder: {f.name}/")
                                    except OSError:
                                        if not silent:
                                            logger.info(f"      ❌ Failed to delete: {f.name}")
                                
                                try:
                                    parent_dir.rmdir()
                                    if not silent:
                                        logger.info(f"   ✅ Folder deleted: {parent_dir.name}/")
                                except OSError:
                                    if not silent:
                                        logger.info(f"   ❌ Failed to delete folder: {parent_dir.name}/")
                except OSError:
                    pass
            
            return True
        except OSError:
            return False

    def add_to_report(self, file_info: FileInfo, deleted: bool, file_hash: Optional[str] = None) -> None:
        """Add file information to the report."""
        if not self.export_report:
            return

        self.report_data['files'].append({
            'name': file_info.path.name,
            'path': str(file_info.path),
            'parent_folder': str(file_info.path.parent),
            'size_bytes': file_info.size,
            'size_mb': round(file_info.size / (1024**2), 2),
            'size_gb': round(file_info.size / (1024**3), 2),
            'mtime': file_info.mtime_str,
            'hash': file_hash or 'unknown',
            'deleted': deleted
        })

    def export_report_json(self) -> None:
        """Export scan report to JSON file."""
        if not self.export_report:
            return

        try:
            self.report_data['orphans_detected'] = len(self.report_data['files'])
            self.report_data['orphans_deleted'] = sum(
                1 for f in self.report_data['files'] if f['deleted']
            )
            self.report_data['total_size_bytes'] = sum(
                f['size_bytes'] for f in self.report_data['files']
            )
            self.report_data['total_size_freed_bytes'] = sum(
                f['size_bytes'] for f in self.report_data['files'] if f['deleted']
            )

            with open(self.export_report, 'w') as f:
                json.dump(self.report_data, f, indent=2)

            logger.info(f"\n📊 Report exported to: {self.export_report}")
        except Exception as e:
            logger.error(f"Failed to export report: {e}")


def main() -> None:
    """Main entry point."""
    try:
        run()
    except KeyboardInterrupt:
        print("\n\n" + "="*60)
        logger.info("⚠️  OPERATION CANCELLED BY USER")
        print("="*60)
        os._exit(1)


def run() -> None:
    """Main execution."""
    parser = ArgumentParser(
        description='Orphan File Sweeper - Delete orphan files without match',
        formatter_class=RawDescriptionHelpFormatter,
        allow_abbrev=False,
        epilog="""Examples:
  %(prog)s -S ~/Downloads -D ~/Films -D ~/Series
  %(prog)s --source /tmp/videos --dest /media/films --dest /backup"""
    )
    
    parser.add_argument('-S', '--source', type=Path, required=False,
                       help='Source directory to analyze')
    parser.add_argument('-D', '--dest', type=Path, action='append', required=False,
                       help='Destination directory (repeatable)')
    parser.add_argument('--config', type=Path,
                       help='Configuration file (JSON/YAML) to load settings from')
    parser.add_argument('--cache', type=Path, default=Path(Config.DEFAULT_CACHE_FILE),
                       help=f'SQLite cache file (default: {Config.DEFAULT_CACHE_FILE})')
    parser.add_argument('--workers', type=int,
                       help='Number of threads for parallel hash (default: auto)')
    parser.add_argument('--auto-delete', action='store_true',
                       help='Automatic deletion without confirmation (DANGEROUS)')
    parser.add_argument('--force-delete-folders', action='store_true',
                       help='Automatically delete non-empty folders without asking')
    parser.add_argument('--dry-run', action='store_true',
                       help='Simulation mode: list orphans without deleting')
    parser.add_argument('--export-report', type=Path,
                       help='Export scan report to JSON file')
    parser.add_argument('--clear-cache', action='store_true',
                       help='Clear cache and quit')
    parser.add_argument('--display-cache', action='store_true',
                       help='Display cache statistics and quit')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Verbose mode: show actions in real-time')
    parser.add_argument('-s', '--silent', action='store_true',
                       help='Silent mode: minimal output')
    
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)
    
    args = parser.parse_args()

    # Load configuration file if provided
    config_data = {}
    if args.config:
        config_data = Config.from_file(args.config)
        logger.info(f"📄 Loaded configuration from: {args.config}")

        # Apply config file settings (CLI args take precedence)
        if not args.source and 'source' in config_data:
            args.source = Path(config_data['source'])
        if not args.dest and 'destinations' in config_data:
            args.dest = [Path(d) for d in config_data['destinations']]
        if not args.workers and 'workers' in config_data:
            args.workers = config_data['workers']

    args.workers = args.workers or os.cpu_count() or 4

    sweeper = OrphanSweeper(
        args.cache,
        args.workers,
        args.verbose,
        args.silent,
        args.export_report
    )
    
    if args.clear_cache:
        sweeper.clear_cache()
        return
    
    if args.display_cache:
        sweeper.display_cache()
        return
    
    if not args.source or not args.dest:
        parser.error("Arguments -S/--source and -D/--dest are required (except with --clear-cache)")
    
    for dest_dir in args.dest:
        if args.source.resolve() == dest_dir.resolve():
            logger.error(f"❌ Source and destination identical: {args.source}")
            sys.exit(1)
    
    if not args.silent:
        print("\n" + "="*60)
        print("🧹 ORPHAN FILE SWEEPER")
        print("="*60)
        logger.info(f"📂 Source: {args.source}")
        logger.info(f"🎯 Destinations: {len(args.dest)} directory(ies)")
        for dest in args.dest:
            logger.info(f"   • {dest}")

    # Store in report
    sweeper.report_data['source'] = str(args.source)
    sweeper.report_data['destinations'] = [str(d) for d in args.dest]

    start_time = time()
    orphans = sweeper.find_orphans(args.source, args.dest)
    scan_duration = time() - start_time
    sweeper.report_data['scan_duration_seconds'] = round(scan_duration, 2)
    
    if not orphans:
        if not args.silent:
            print("\n" + "="*60)
            logger.info("✅ NO ORPHAN FILE DETECTED")
            print("="*60)
            logger.info(f"🎉 All source files have a match!")
            logger.info(f"⏱️  Scan duration: {scan_duration:.1f}s")
        return
    
    if not args.silent:
        print("\n" + "="*60)
        logger.info(f"⚠️  {len(orphans)} ORPHAN FILE(S) DETECTED")
        print("="*60)
        total_size = sum(o.size for o in orphans)
        logger.info(f"💾 Total size: {total_size / (1024**2):.2f} MB ({total_size / (1024**3):.2f} GB)")
        logger.info(f"⏱️  Scan duration: {scan_duration:.1f}s")
    
    deleted_files: List[FileInfo] = []
    yes_to_all = False
    for orphan in orphans:
        if yes_to_all:
            should_delete = True
        else:
            should_delete, yes_to_all = sweeper.confirm_deletion(orphan, args.auto_delete, args.dry_run, args.silent)

        if should_delete:
            if sweeper.delete_file(orphan.path, args.dry_run, args.force_delete_folders, args.silent):
                deleted_files.append(orphan)
                sweeper.add_to_report(orphan, deleted=True)
        else:
            sweeper.add_to_report(orphan, deleted=False)
    
    if not args.silent:
        print("\n" + "="*60)
        logger.info("📋 SUMMARY")
        print("="*60)
        logger.info(f"📊 Orphan files detected: {len(orphans)}")
        if args.dry_run:
            logger.info(f"🔍 [DRY-RUN] Files that would be deleted: {len(deleted_files)}")
        else:
            logger.info(f"🗑️  Files deleted: {len(deleted_files)}")
            logger.info(f"⏭️  Files skipped: {len(orphans) - len(deleted_files)}")
        
        deleted_size = sum(f.size for f in deleted_files)
        logger.info(f"💾 Space freed: {deleted_size / (1024**2):.2f} MB ({deleted_size / (1024**3):.2f} GB)")
        logger.info(f"⏱️  Total duration: {time() - start_time:.1f}s")
        print("="*60 + "\n")

    # Export report if requested
    sweeper.export_report_json()


if __name__ == "__main__":
    main()