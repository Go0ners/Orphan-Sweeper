#!/usr/bin/env python3
"""
Orphan File Sweeper - Supprime les fichiers vidéo orphelins sans correspondance.
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
import sys
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from threading import Lock
from time import time
from typing import List, Optional, Set
from queue import Queue
import os
import shutil
import select

# Configuration du logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class FileInfo:
    """Informations d'un fichier vidéo."""
    
    def __init__(self, path: Path, size: int, mtime: float) -> None:
        self.path = path
        self.size = size
        self.mtime = mtime
    
    @property
    def name(self) -> str:
        return self.path.name
    
    @property
    def mtime_str(self) -> str:
        return datetime.fromtimestamp(self.mtime).strftime('%Y-%m-%d %H:%M:%S')


class OrphanSweeper:
    """Détecteur et suppresseur de fichiers vidéo orphelins."""
    
    VIDEO_EXTENSIONS: Set[str] = {
        '.mkv', '.mp4', '.avi', '.mov', '.wmv', 
        '.flv', '.webm', '.m4v'
    }
    
    def __init__(self, cache_file: Path = Path("media_cache.db"), max_workers: int = 4, verbose: bool = False) -> None:
        self.cache_file = cache_file
        self.conn = self._init_db()
        self.max_workers = max_workers
        self.db_lock = Lock()
        self.pending_commits: list[tuple] = []
        self.verbose = verbose
        self.log_queue: Queue = Queue()
    
    def __del__(self) -> None:
        """Ferme la connexion SQLite."""
        if hasattr(self, 'conn'):
            self.conn.close()
    
    def _init_db(self) -> sqlite3.Connection:
        """Initialise la base SQLite."""
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
        """Vide le cache."""
        self.conn.execute("DELETE FROM file_cache")
        self.conn.commit()
        logger.info(f"\n✅ Cache vidé: {self.cache_file}")
    
    def _get_file_hash(self, file_path: Path) -> Optional[str]:
        """Calcule le hash MD5 d'un fichier avec cache (hash partiel pour gros fichiers)."""
        try:
            stat = file_path.stat()
        except OSError as e:
            logger.error(f"⚠️  Erreur accès {file_path.name}: {e}")
            return None
        
        path_str = str(file_path)
        file_size = stat.st_size
        
        # Vérifier cache (lecture thread-safe)
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
                self.log_queue.put(f"🔐 Calcul hash: {file_path.name}")
            
            hasher = hashlib.md5()
            
            # Hash partiel pour fichiers > 100 MB
            if file_size > 100 * 1024 * 1024:
                chunk_size = 10 * 1024 * 1024  # 10 MB
                with file_path.open('rb') as f:
                    # Premiers 10 MB
                    hasher.update(f.read(chunk_size))
                    
                    # Milieu 10 MB
                    f.seek(file_size // 2 - chunk_size // 2)
                    hasher.update(f.read(chunk_size))
                    
                    # Derniers 10 MB
                    f.seek(max(0, file_size - chunk_size))
                    hasher.update(f.read(chunk_size))
            else:
                # Hash complet pour petits fichiers
                with file_path.open('rb') as f:
                    while chunk := f.read(1048576):  # 1MB buffer
                        hasher.update(chunk)
            
            file_hash = hasher.hexdigest()
            
            # Ajouter au batch (écriture thread-safe)
            with self.db_lock:
                self.pending_commits.append((path_str, stat.st_mtime, stat.st_size, file_hash))
                # Flush périodique tous les 100 fichiers
                if len(self.pending_commits) >= 100:
                    self.conn.executemany(
                        "INSERT OR REPLACE INTO file_cache (path, mtime, size, hash) VALUES (?, ?, ?, ?)",
                        self.pending_commits
                    )
                    self.conn.commit()
                    self.pending_commits.clear()
            
            return file_hash
            
        except (OSError, IOError) as e:
            logger.error(f"⚠️  Erreur hash {file_path.name}: {e}")
            return None
    
    def _flush_cache(self) -> None:
        """Commit tous les hash en attente."""
        with self.db_lock:
            if self.pending_commits:
                self.conn.executemany(
                    "INSERT OR REPLACE INTO file_cache (path, mtime, size, hash) VALUES (?, ?, ?, ?)",
                    self.pending_commits
                )
                self.conn.commit()
                self.pending_commits.clear()
    
    def _scan_directory(self, directory: Path) -> List[FileInfo]:
        """Scanne un répertoire et retourne les infos des fichiers vidéo."""
        if not directory.exists():
            logger.error(f"❌ Répertoire inexistant: {directory}")
            return []
        
        logger.info(f"📁 Scan: {directory}")
        files_info: List[FileInfo] = []
        
        for file_path in directory.rglob("*"):
            if not (file_path.is_file() and 
                   file_path.suffix.lower() in self.VIDEO_EXTENSIONS):
                continue
            
            try:
                stat = file_path.stat()
                # Ignorer fichiers < 350 MB
                if stat.st_size < 350 * 1024 * 1024:
                    continue
                # Ignorer fichiers avec 'sample' dans le nom
                if 'sample' in file_path.name.lower():
                    continue
                
                files_info.append(FileInfo(
                    path=file_path,
                    size=stat.st_size,
                    mtime=stat.st_mtime
                ))
                if self.verbose:
                    logger.info(f"   📄 Trouvé: {file_path.name}")
            
            except OSError as e:
                logger.error(f"⚠️  Erreur fichier {file_path}: {e}")
        
        return files_info
    
    def find_orphans(self, source_dir: Path, dest_dirs: List[Path]) -> List[FileInfo]:
        """Trouve les fichiers orphelins dans le répertoire source."""
        # Validation
        for dest_dir in dest_dirs:
            if source_dir.resolve() == dest_dir.resolve():
                logger.error(f"❌ Source et destination identiques: {source_dir}")
                sys.exit(1)
        
        logger.info("\n" + "="*60)
        logger.info("🔍 ANALYSE DES FICHIERS")
        logger.info("="*60)
        
        # Scan source
        source_files = self._scan_directory(source_dir)
        logger.info(f"   Source: {len(source_files)} fichiers")
        
        # Scan destinations
        dest_files: List[FileInfo] = []
        for dest_dir in dest_dirs:
            dest_info = self._scan_directory(dest_dir)
            dest_files.extend(dest_info)
            logger.info(f"   Destination: {len(dest_info)} fichiers")
        
        logger.info(f"\n📊 Total destinations: {len(dest_files)} fichiers")
        
        # Index destinations par (taille, mtime) pour filtre rapide
        dest_metadata = {(f.size, f.mtime) for f in dest_files}
        
        # Filtre 1: éliminer les fichiers avec taille+mtime identiques
        candidates = [
            f for f in source_files 
            if (f.size, f.mtime) not in dest_metadata
        ]
        
        logger.info(f"⚡ Filtre rapide: {len(candidates)} candidats orphelins")
        
        if not candidates:
            return []
        
        # Filtre 2: hash candidats
        max_cpu = os.cpu_count() or 1
        logger.info(f"\n🔐 Calcul hash pour {len(candidates)} candidats ({self.max_workers}/{max_cpu} threads)...")
        candidate_hashes = self._compute_hashes_parallel(candidates)
        
        # Optimisation: ne hasher que les destinations avec taille correspondante
        candidate_sizes = {f.size for f in candidates}
        dest_to_hash = [f for f in dest_files if f.size in candidate_sizes]
        
        logger.info(f"\n🔐 Calcul hash pour {len(dest_to_hash)} destinations ({self.max_workers}/{max_cpu} threads)...")
        dest_hash_map = self._compute_hashes_parallel(dest_to_hash)
        dest_hashes = set(dest_hash_map.keys())
        
        # Flush cache
        self._flush_cache()
        
        # Orphelins = candidats dont le hash n'existe pas en destination
        orphans = [
            file_info for file_hash, file_info in candidate_hashes.items()
            if file_hash not in dest_hashes
        ]
        
        # Pause pour validation
        if orphans:
            print(f"\n⏸️  {len(orphans)} orphelin(s) détecté(s). Appuyez sur Entrée pour continuer (auto dans 10s)...")
            if sys.stdin.isatty():
                ready, _, _ = select.select([sys.stdin], [], [], 10)
                if ready:
                    sys.stdin.readline()
            else:
                time.sleep(10)
        
        return orphans
    
    def confirm_deletion(self, file_info: FileInfo, auto_delete: bool = False, dry_run: bool = False) -> tuple[bool, bool]:
        """Demande confirmation pour supprimer un fichier. Retourne (supprimer, yes_to_all)."""
        print(f"\n{'─'*60}")
        print(f"🗑️  FICHIER ORPHELIN DÉTECTÉ")
        print(f"{'─'*60}")
        print(f"📄 Fichier: {file_info.path.name}")
        print(f"📂 Chemin: {file_info.path.parent}")
        print(f"💾 Taille: {file_info.size:,} bytes ({file_info.size / (1024**2):.2f} MB)")
        print(f"📅 Date: {file_info.mtime_str}")
        print(f"\n⚠️  Ce fichier n'existe dans aucune destination.")
        
        if dry_run:
            print("\n🔍 [DRY-RUN] Serait supprimé")
            return (True, False)
        
        if auto_delete:
            print("\n⚡ Suppression automatique activée")
            return (True, False)
        
        while True:
            choice = input("\n❓ Supprimer ce fichier? ([O]ui/n/a/q): ").lower().strip()
            if choice in ('', 'o', 'oui'):
                return (True, False)
            elif choice in ('n', 'non'):
                return (False, False)
            elif choice in ('a', 'all', 'tout'):
                print("\n⚡ Suppression de tous les fichiers restants")
                return (True, True)
            elif choice == 'q':
                print("\n👋 Abandon de l'opération")
                sys.exit(0)
            print("⚠️  Réponse invalide. Utilisez: o (oui) / n (non) / a (tout) / q (quitter)")
    
    def _compute_hashes_parallel(self, files: List[FileInfo]) -> dict[str, FileInfo]:
        """Calcule les hash en parallèle avec progression."""
        result = {}
        total = len(files)
        completed = 0
        start_time = time()
        executor = ThreadPoolExecutor(max_workers=self.max_workers)
        
        # Obtenir hauteur terminal pour mode verbose
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
                except Exception as e:
                    if self.verbose:
                        self.log_queue.put(f"⚠️  Erreur hash {file_info.path.name}: {e}")
                
                # Calculer progression
                elapsed = time() - start_time
                percent = (completed / total) * 100
                rate = completed / elapsed if elapsed > 0 else 0
                eta_seconds = (total - completed) / rate if rate > 0 else 0
                
                # Formater ETA
                if eta_seconds < 60:
                    eta_str = f"{eta_seconds:.0f}s"
                elif eta_seconds < 3600:
                    eta_str = f"{eta_seconds/60:.0f}min"
                else:
                    eta_str = f"{eta_seconds/3600:.1f}h"
                
                progress_line = f"   ⏳ Progression: {completed}/{total} ({percent:.1f}%) | ⚡ {rate:.1f} fichiers/s | ⏱️  ETA: {eta_str}"
                
                # Afficher logs puis progression
                if self.verbose:
                    # Vider tous les logs d'abord
                    logs = []
                    while not self.log_queue.empty():
                        logs.append(self.log_queue.get())
                    
                    if logs:
                        # Effacer ligne de progression, afficher logs, réafficher progression
                        if term_height > 0:
                            sys.stdout.write(f"\033[{term_height};0H\033[K")
                        for log_msg in logs:
                            print(log_msg)
                    
                    # Afficher progression en bas
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
        else:
            sys.stdout.write("\n")
        sys.stdout.flush()
        return result
    
    def delete_file(self, file_path: Path, dry_run: bool = False) -> bool:
        """Supprime un fichier et son dossier parent si le nom correspond."""
        parent_dir = file_path.parent
        file_stem = file_path.stem  # Nom sans extension
        should_delete_parent = parent_dir.name == file_stem
        
        if dry_run:
            logger.info(f"   🔍 [DRY-RUN] {file_path.name}")
            if should_delete_parent:
                logger.info(f"   🔍 [DRY-RUN] Dossier: {parent_dir.name}/")
            return True
        
        try:
            file_path.unlink()
            logger.info(f"   ✅ Supprimé: {file_path.name}")
            
            # Supprimer le dossier parent si nom identique et vide
            if should_delete_parent:
                try:
                    # Vérifier si le dossier est vide
                    if not any(parent_dir.iterdir()):
                        parent_dir.rmdir()
                        logger.info(f"   ✅ Dossier supprimé: {parent_dir.name}/")
                    else:
                        logger.info(f"   ⚠️  Dossier non vide, conservé: {parent_dir.name}/")
                except OSError as e:
                    logger.error(f"   ❌ Erreur dossier: {parent_dir.name}/ - {e}")
            
            return True
        except OSError as e:
            logger.error(f"   ❌ Erreur: {file_path.name} - {e}")
            return False


def main() -> None:
    """Point d'entrée principal."""
    try:
        run()
    except KeyboardInterrupt:
        print("\n\n" + "="*60)
        logger.info("⚠️  OPÉRATION ANNULÉE PAR L'UTILISATEUR")
        print("="*60)
        logger.info("👋 Aucune modification effectuée")
        os._exit(1)


def run() -> None:
    """Exécution principale."""
    parser = ArgumentParser(
        description='Orphan File Sweeper - Supprime les fichiers orphelins sans correspondance',
        formatter_class=RawDescriptionHelpFormatter,
        allow_abbrev=False,
        epilog="""Exemples:
  %(prog)s -S ~/Downloads -D ~/Films -D ~/Series
  %(prog)s --source /tmp/videos --dest /media/films --dest /backup"""
    )
    
    parser.add_argument('-S', '--source', type=Path, required=False,
                       help='Répertoire source à analyser')
    parser.add_argument('-D', '--dest', type=Path, action='append', required=False,
                       help='Répertoire de destination (peut être répété)')
    parser.add_argument('--cache', type=Path, default=Path('media_cache.db'),
                       help='Fichier cache SQLite (défaut: media_cache.db)')
    parser.add_argument('--workers', type=int, default=None,
                       help='Nombre de threads pour calcul hash parallèle (défaut: auto)')
    parser.add_argument('--auto-delete', action='store_true',
                       help='Suppression automatique sans confirmation (DANGEREUX)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Mode simulation : liste les orphelins sans supprimer')
    parser.add_argument('--clear-cache', action='store_true',
                       help='Vider le cache et quitter')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Mode verbose : affiche les actions en temps réel')
    
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)
    
    args = parser.parse_args()
    
    # Auto-detect optimal workers: cpu_count pour I/O bound
    if args.workers is None:
        args.workers = os.cpu_count() or 4
    
    sweeper = OrphanSweeper(args.cache, args.workers, args.verbose)
    
    if args.clear_cache:
        sweeper.clear_cache()
        return
    
    if not args.source or not args.dest:
        parser.error("Les arguments -S/--source et -D/--dest sont requis (sauf avec --clear-cache)")
    
    print("\n" + "="*60)
    print("🧹 ORPHAN FILE SWEEPER")
    print("="*60)
    logger.info(f"📂 Source: {args.source}")
    logger.info(f"🎯 Destinations: {len(args.dest)} répertoire(s)")
    for dest in args.dest:
        logger.info(f"   • {dest}")
    
    start_time = time()
    orphans = sweeper.find_orphans(args.source, args.dest)
    scan_duration = time() - start_time
    
    if not orphans:
        print("\n" + "="*60)
        logger.info("✅ AUCUN FICHIER ORPHELIN DÉTECTÉ")
        print("="*60)
        logger.info(f"🎉 Tous les fichiers source ont une correspondance!")
        logger.info(f"⏱️  Durée du scan: {scan_duration:.1f}s")
        return
    
    print("\n" + "="*60)
    logger.info(f"⚠️  {len(orphans)} FICHIER(S) ORPHELIN(S) DÉTECTÉ(S)")
    print("="*60)
    total_size = sum(o.size for o in orphans)
    logger.info(f"💾 Taille totale: {total_size / (1024**2):.2f} MB ({total_size / (1024**3):.2f} GB)")
    logger.info(f"⏱️  Durée du scan: {scan_duration:.1f}s")
    
    deleted_files: list[FileInfo] = []
    yes_to_all = False
    for orphan in orphans:
        if yes_to_all:
            should_delete = True
        else:
            should_delete, yes_to_all = sweeper.confirm_deletion(orphan, args.auto_delete, args.dry_run)
        
        if should_delete:
            if sweeper.delete_file(orphan.path, args.dry_run):
                deleted_files.append(orphan)
    
    print("\n" + "="*60)
    logger.info("📋 RÉSUMÉ")
    print("="*60)
    logger.info(f"📊 Fichiers orphelins détectés: {len(orphans)}")
    if args.dry_run:
        logger.info(f"🔍 [DRY-RUN] Fichiers qui seraient supprimés: {len(deleted_files)}")
    else:
        logger.info(f"🗑️  Fichiers supprimés: {len(deleted_files)}")
        logger.info(f"⏭️  Fichiers ignorés: {len(orphans) - len(deleted_files)}")
    
    deleted_size = sum(f.size for f in deleted_files)
    logger.info(f"💾 Espace libéré: {deleted_size / (1024**2):.2f} MB ({deleted_size / (1024**3):.2f} GB)")
    logger.info(f"⏱️  Durée totale: {time() - start_time:.1f}s")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()