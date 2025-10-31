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
from typing import List, Optional, Set, Tuple

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
    
    def __init__(self, cache_file: Path = Path("media_cache.db"), max_workers: int = 4) -> None:
        self.cache_file = cache_file
        self.conn = self._init_db()
        self.max_workers = max_workers
        self.db_lock = Lock()
    
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
    
    def _get_file_hash(self, file_path: Path, show_log: bool = False) -> Optional[str]:
        """Calcule le hash MD5 d'un fichier avec cache."""
        try:
            stat = file_path.stat()
            path_str = str(file_path)
            
            # Vérifier cache (lecture thread-safe)
            with self.db_lock:
                cursor = self.conn.execute(
                    "SELECT hash FROM file_cache WHERE path=? AND mtime=? AND size=?",
                    (path_str, stat.st_mtime, stat.st_size)
                )
                row = cursor.fetchone()
                if row:
                    return row[0]
            
            if show_log:
                logger.info(f"Calcul hash: {file_path.name}")
            
            hasher = hashlib.md5()
            with file_path.open('rb') as f:
                while chunk := f.read(8192):
                    hasher.update(chunk)
            
            file_hash = hasher.hexdigest()
            
            # Sauvegarder dans cache (écriture thread-safe)
            with self.db_lock:
                self.conn.execute(
                    "INSERT OR REPLACE INTO file_cache (path, mtime, size, hash) VALUES (?, ?, ?, ?)",
                    (path_str, stat.st_mtime, stat.st_size, file_hash)
                )
                self.conn.commit()
            
            return file_hash
            
        except (OSError, IOError) as e:
            logger.error(f"⚠️  Erreur hash {file_path.name}: {e}")
            return None
    
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
                files_info.append(FileInfo(
                    path=file_path,
                    size=stat.st_size,
                    mtime=stat.st_mtime
                ))
            
            except OSError as e:
                logger.error(f"⚠️  Erreur fichier {file_path}: {e}")
        
        return files_info
    
    def find_orphans(self, source_dir: Path, dest_dirs: List[Path]) -> List[FileInfo]:
        """Trouve les fichiers orphelins dans le répertoire source."""
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
        
        # Filtre 2: hash en parallèle pour les candidats restants
        logger.info(f"\n🔐 Calcul hash pour {len(candidates)} candidats ({self.max_workers} threads)...")
        candidate_hashes = self._compute_hashes_parallel(candidates)
        
        # Hash destinations en parallèle si nécessaire
        logger.info(f"\n🔐 Calcul hash pour {len(dest_files)} destinations ({self.max_workers} threads)...")
        dest_hash_map = self._compute_hashes_parallel(dest_files)
        dest_hashes = set(dest_hash_map.keys())
        
        # Orphelins = candidats dont le hash n'existe pas en destination
        orphans = [
            file_info for file_hash, file_info in candidate_hashes.items()
            if file_hash not in dest_hashes
        ]
        
        return orphans
    
    def confirm_deletion(self, file_info: FileInfo, auto_delete: bool = False, dry_run: bool = False) -> bool:
        """Demande confirmation pour supprimer un fichier."""
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
            return True
        
        if auto_delete:
            print("\n⚡ Suppression automatique activée")
            return True
        
        while True:
            choice = input("\n❓ Supprimer ce fichier? ([O]ui/n/q): ").lower().strip()
            if choice in ('', 'o', 'oui'):
                return True
            elif choice in ('n', 'non'):
                return False
            elif choice == 'q':
                print("\n👋 Abandon de l'opération")
                sys.exit(0)
            print("⚠️  Réponse invalide. Utilisez: o (oui) / n (non) / q (quitter)")
    
    def _compute_hashes_parallel(self, files: List[FileInfo]) -> dict[str, FileInfo]:
        """Calcule les hash en parallèle avec progression."""
        result = {}
        total = len(files)
        completed = 0
        start_time = time()
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self._get_file_hash, f.path): f for f in files}
            
            for future in as_completed(futures):
                file_info = futures[future]
                completed += 1
                
                try:
                    file_hash = future.result()
                    if file_hash:
                        result[file_hash] = file_info
                except Exception as e:
                    sys.stdout.write(f"\n⚠️  Erreur hash {file_info.path.name}: {e}\n")
                    sys.stdout.flush()
                
                # Afficher progression
                elapsed = time() - start_time
                percent = (completed / total) * 100
                rate = completed / elapsed if elapsed > 0 else 0
                eta = (total - completed) / rate if rate > 0 else 0
                
                sys.stdout.write(f"\r   ⏳ Progression: {completed}/{total} ({percent:.1f}%) | "
                                f"⚡ {rate:.1f} fichiers/s | ⏱️  ETA: {eta:.0f}s")
                sys.stdout.flush()
        
        sys.stdout.write("\n")
        sys.stdout.flush()
        return result
    
    def delete_file(self, file_path: Path, dry_run: bool = False) -> bool:
        """Supprime un fichier."""
        if dry_run:
            logger.info(f"   🔍 [DRY-RUN] {file_path.name}")
            return True
        
        try:
            file_path.unlink()
            logger.info(f"   ✅ Supprimé: {file_path.name}")
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
        sys.exit(0)


def run() -> None:
    """Exécution principale."""
    parser = ArgumentParser(
        description='Orphan File Sweeper - Supprime les fichiers orphelins sans correspondance',
        formatter_class=RawDescriptionHelpFormatter,
        epilog="""Exemples:
  %(prog)s -S ~/Downloads -D ~/Films -D ~/Series
  %(prog)s --source /tmp/videos --destination /media/films --destination /backup"""
    )
    
    parser.add_argument('-S', '--source', type=Path,
                       help='Répertoire source à analyser')
    parser.add_argument('-D', '--destination', type=Path, action='append',
                       help='Répertoire de destination (peut être répété)')
    parser.add_argument('--cache', type=Path, default=Path('media_cache.db'),
                       help='Fichier cache SQLite (défaut: media_cache.db)')
    parser.add_argument('--workers', type=int, default=4,
                       help='Nombre de threads pour calcul hash parallèle (défaut: 4)')
    parser.add_argument('--auto-delete', action='store_true',
                       help='Suppression automatique sans confirmation (DANGEREUX)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Mode simulation : liste les orphelins sans supprimer')
    parser.add_argument('--clear-cache', action='store_true',
                       help='Vider le cache et quitter')
    
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)
    
    args = parser.parse_args()
    
    sweeper = OrphanSweeper(args.cache, args.workers)
    
    if args.clear_cache:
        sweeper.clear_cache()
        return
    
    if not args.source or not args.destination:
        parser.error("Les arguments -S/--source et -D/--destination sont requis (sauf avec --clear-cache)")
    
    print("\n" + "="*60)
    print("🧹 ORPHAN FILE SWEEPER")
    print("="*60)
    logger.info(f"📂 Source: {args.source}")
    logger.info(f"🎯 Destinations: {len(args.destination)} répertoire(s)")
    for dest in args.destination:
        logger.info(f"   • {dest}")
    
    start_time = time()
    orphans = sweeper.find_orphans(args.source, args.destination)
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
    
    deleted_count = 0
    for orphan in orphans:
        if sweeper.confirm_deletion(orphan, args.auto_delete, args.dry_run):
            if sweeper.delete_file(orphan.path, args.dry_run):
                deleted_count += 1
    
    print("\n" + "="*60)
    logger.info("📋 RÉSUMÉ")
    print("="*60)
    logger.info(f"📊 Fichiers orphelins détectés: {len(orphans)}")
    if args.dry_run:
        logger.info(f"🔍 [DRY-RUN] Fichiers qui seraient supprimés: {deleted_count}")
    else:
        logger.info(f"🗑️  Fichiers supprimés: {deleted_count}")
        logger.info(f"⏭️  Fichiers ignorés: {len(orphans) - deleted_count}")
    
    deleted_size = sum(o.size for o in orphans[:deleted_count])
    logger.info(f"💾 Espace libéré: {deleted_size / (1024**2):.2f} MB ({deleted_size / (1024**3):.2f} GB)")
    logger.info(f"⏱️  Durée totale: {time() - start_time:.1f}s")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()