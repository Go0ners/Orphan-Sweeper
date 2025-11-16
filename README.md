# 🧹 Orphan File Sweeper

Detects and deletes orphan video files from the source directory that have no match in destination directories.

**Latest update:** Major improvements - configuration files support, JSON reports export, improved logging, and comprehensive test suite.

## ⚠️ Warning

**THIS TOOL PERMANENTLY DELETES FILES**

- ❌ No recycle bin - permanent deletion
- ❌ No recovery possible
- ✅ **ALWAYS test with `--dry-run` first**
- ✅ Backup your important data

## 🚀 Installation

```bash
# No dependencies - Python 3.8+ required
python3 --version
python3 orphan_sweeper.py --help
```

## 🆕 New Features

### Configuration Files
Load settings from JSON or YAML configuration files:
```bash
# Create a config file (see config.example.json or config.example.yml)
python3 orphan_sweeper.py --config my_config.yml
```

### JSON Report Export
Export detailed scan reports for auditing and automation:
```bash
python3 orphan_sweeper.py -S ~/Downloads -D ~/Movies --export-report report.json
```

The report includes:
- Scan date and duration
- Source and destination paths
- List of all orphan files with metadata
- Total size and space freed
- Deletion status for each file

### Improved Logging
Structured logging with timestamps for better debugging and audit trails.

### Test Suite
Comprehensive unit tests to ensure reliability:
```bash
python3 -m unittest discover tests
```

## 📖 Usage

### Recommended Workflow

```bash
# 1. Test (mandatory)
python3 orphan_sweeper.py -S ~/Downloads -D ~/Movies --dry-run

# 2. Review the file list

# 3. Real execution with confirmation
python3 orphan_sweeper.py --source ~/Downloads --dest ~/Movies
```

### Examples

```bash
# Multiple destinations
python3 orphan_sweeper.py -S ~/Downloads -D ~/Movies -D ~/Shows

# Optimization (32 threads for NAS/network)
python3 orphan_sweeper.py --source /source --dest /dest --workers 32

# Automatic deletion (DANGER)
python3 orphan_sweeper.py -S ~/temp -D ~/archive --auto-delete

# Clear cache
python3 orphan_sweeper.py --clear-cache

# Display cache statistics
python3 orphan_sweeper.py --display-cache
```

## 🔍 How does it work?

### Logic

A file is **orphan** if:
- It exists in SOURCE and does NOT exist in ANY destination

### Automatic subdirectory matching

If source and destinations have common subdirectories, the script automatically compares them:

```
Source: /torrents/          Dest: /media/
  ├── movies/              ├── movies/
  ├── shows/               ├── shows/
  ├── 4k/                  └── 4k/
  └── incomplete/

→ Automatically compares:
  - torrents/movies ↔ media/movies
  - torrents/shows ↔ media/shows
  - torrents/4k ↔ media/4k
  - incomplete/ ignored (not in dest)
```

Generic: works with any folder names!

### Algorithm

```
1. SCAN
   └─> Collect metadata (size, mtime)

2. FAST FILTER
   └─> Eliminate identical files (size + mtime)
   └─> Savings: ~90% of hash calculations

3. PARTIAL MD5 HASH
   └─> Hash 30MB (10MB start + 10MB middle + 10MB end)
   └─> Parallel computation (multi-threading)
   └─> SQLite cache to avoid recalculations
   └─> Precise comparison by hash

4. DETECTION
   └─> Source files without match

5. DELETION
   └─> Manual confirmation (except --auto-delete)
```

### Why MD5?

- ✅ Detects identical files even if renamed
- ✅ `movie.mp4` = `movie_renamed.mp4` if hash identical
- ✅ No false positives

## ✨ Features

- 🔍 Recursive scan
- 🎬 Multi-format support (mkv, mp4, avi, mov, wmv, flv, webm, m4v)
- 🔐 Partial MD5 hash (30MB: start + middle + end)
- 🔗 Automatic matching of common subdirectories
- 🛡️ Ignores files < 350MB and samples
- 📁 Auto-delete parent folder if name matches
- 💾 SQLite cache with batch commits
- ⚡ Multi-threading (auto: CPU threads by default)
- 📊 Progress bar with ETA and threads
- 🔍 Dry-run mode (simulation)
- 💬 Verbose mode with thread-safe queue
- ⚠️ Manual confirmation by default
- 🚀 Option 'a' to delete all (yes to all)
- ⏸️ Validation pause after detection

## 📊 Options

| Option | Description | Default |
|--------|-------------|---------|
| `-S, --source` | Source directory | Required |
| `-D, --dest` | Destination (repeatable) | Required |
| `--config` | Config file (JSON/YAML) | None |
| `--cache` | SQLite cache file | `media_cache.db` |
| `--workers` | Threads for hashing | `auto` (CPU) |
| `--dry-run` | Simulation without deletion | `False` |
| `--auto-delete` | No confirmation ⚠️ | `False` |
| `--force-delete-folders` | Auto-delete non-empty folders | `False` |
| `--export-report` | Export report to JSON file | None |
| `--clear-cache` | Clear cache | `False` |
| `--display-cache` | Display cache statistics | `False` |
| `-v, --verbose` | Show actions in real-time | `False` |
| `-s, --silent` | Minimal output | `False` |

## 💡 Output Example

```
🧹 ORPHAN FILE SWEEPER
============================================================
📂 Source: /mnt/data/torrents
🎯 Destinations: 1 directory(ies)
   • /mnt/data/media

🔗 Matched subdirs with media: 4k, movies, shows

🔍 FILE ANALYSIS
============================================================
📁 Scan: /mnt/data/torrents/movies
   Source: 2194 files
📁 Scan: /mnt/data/media/movies
   Destination: 2560 files

📊 Total destinations: 2560 files
⚡ Fast filter: 311 orphan candidates

🔐 Calculating hash for 311 candidates...
   ⏳ Progress: 311/311 (100.0%) | ⚡ 589.1 files/s | 💻 16/16 threads | ⏱️  ETA: 0s

🔐 Calculating hash for 160 destinations...
   ⏳ Progress: 160/160 (100.0%) | ⚡ 11112.5 files/s | 💻 16/16 threads | ⏱️  ETA: 0s

⏸️  30 orphan(s) detected. Press Enter to continue...

⚠️  30 ORPHAN FILE(S) DETECTED
============================================================
💾 Total size: 245.00 GB (245.00 GB)
⏱️  Scan duration: 12.3s

────────────────────────────────────────────────────────────
🗑️  ORPHAN FILE DETECTED
────────────────────────────────────────────────────────────
📄 File: Jurassic.World.Rebirth.2025.mkv
📂 Path: /mnt/data/torrents/movies/Jurassic.World.Rebirth.2025
💾 Size: 8,589,934,592 bytes (8192.00 MB)
📅 Date: 2025-01-15 14:23:45

⚠️  This file does not exist in any destination.

❓ Delete this file? ([Y]es/n/a/q): y
   ✅ Deleted: Jurassic.World.Rebirth.2025.mkv
   ✅ Folder deleted: Jurassic.World.Rebirth.2025/
```

## 💡 Confirmation Options

When deleting, you can answer:
- **y** (yes) : Delete this file
- **n** (no) : Skip this file
- **a** (all) : Delete all remaining files without asking
- **q** (quit) : Abort operation

## ⚡ Performance

### Automatic optimizations

- 1MB buffer for file reading (16x fewer system calls)
- Auto threads = number of CPUs (I/O bound)
- SQLite cache with batch commits
- Fast filter by size+mtime (~90% files avoided)

### Storage adjustment

```bash
# Local SSD/NVMe disk (optimal default)
python3 orphan_sweeper.py -S /source -D /dest

# NAS/network (increase threads to compensate latency)
python3 orphan_sweeper.py -S /nas/source -D /nas/dest --workers 32

# Slow mechanical HDD (reduce threads)
python3 orphan_sweeper.py -S /source -D /dest --workers 8
```

### Expected speed

- Local SSD: 50-100 files/s
- Gigabit NAS: 5-20 files/s
- Mechanical HDD: 10-30 files/s

## 📄 License

Code generated by **Amazon Q Developer** (AWS).

**Use at your own risk** - No liability for data loss.
