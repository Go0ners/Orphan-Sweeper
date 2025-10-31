# 🧹 Orphan File Sweeper

 Détecte et supprime les fichiers vidéo orphelins du répertoire source qui n'ont aucune correspondance dans les répertoires de destination.

## ⚠️ Avertissement

**CET OUTIL SUPPRIME DÉFINITIVEMENT DES FICHIERS**

- ❌ Pas de corbeille - suppression définitive
- ❌ Pas de récupération possible
- ✅ **Testez TOUJOURS avec `--dry-run` d'abord**
- ✅ Sauvegardez vos données importantes

## 🚀 Installation

```bash
# Aucune dépendance - Python 3.8+ requis
python3 --version
python3 orphan_sweeper.py --help
```

## 📖 Usage

### Workflow recommandé

```bash
# 1. Test (obligatoire)
python3 orphan_sweeper.py -S ~/Downloads -D ~/Films --dry-run

# 2. Vérifier la liste des fichiers

# 3. Exécution réelle avec confirmation
python3 orphan_sweeper.py --source ~/Downloads --dest ~/Films
```

### Exemples

```bash
# Plusieurs destinations
python3 orphan_sweeper.py -S ~/Downloads -D ~/Films -D ~/Series

# Optimisation (32 threads pour NAS/réseau)
python3 orphan_sweeper.py --source /source --dest /dest --workers 32

# Suppression automatique (DANGER)
python3 orphan_sweeper.py -S ~/temp -D ~/archive --auto-delete

# Vider le cache
python3 orphan_sweeper.py --clear-cache
```

## 🔍 Comment ça marche ?

### Logique

Un fichier est **orphelin** si :
- Il existe dans SOURCE et qu'il n'existe dans AUCUNE destination

### Matching automatique des sous-dossiers

Si source et destinations ont des sous-dossiers communs, le script les compare automatiquement :

```
Source: /torrents/          Dest: /media/
  ├── movies/              ├── movies/
  ├── shows/               ├── shows/
  ├── 4k/                  └── 4k/
  └── incomplete/

→ Compare automatiquement :
  - torrents/movies ↔ media/movies
  - torrents/shows ↔ media/shows
  - torrents/4k ↔ media/4k
  - incomplete/ ignoré (pas dans dest)
```

Générique : fonctionne avec n'importe quels noms de dossiers !

### Algorithme

```
1. SCAN
   └─> Collecte métadonnées (taille, mtime)

2. FILTRE RAPIDE
   └─> Élimine fichiers identiques (taille + mtime)
   └─> Économie : ~90% des calculs hash

3. HASH MD5 PARTIEL
   └─> Hash 30MB (10MB début + 10MB milieu + 10MB fin)
   └─> Calcul parallèle (multi-threading)
   └─> Cache SQLite pour éviter recalculs
   └─> Comparaison précise par hash

4. DÉTECTION
   └─> Fichiers source sans correspondance

5. SUPPRESSION
   └─> Confirmation manuelle (sauf --auto-delete)
```

### Pourquoi MD5 ?

- ✅ Détecte fichiers identiques même renommés
- ✅ `film.mp4` = `movie_renamed.mp4` si hash identique
- ✅ Pas de faux positifs

## ✨ Fonctionnalités

- 🔍 Scan récursif
- 🎬 Support multi formats (mkv, mp4, avi, mov, wmv, flv, webm, m4v)
- 🔐 Hash MD5 partiel (30MB : début + milieu + fin)
- 🔗 Matching automatique des sous-dossiers communs
- 🛡️ Ignore fichiers < 350MB et samples
- 📁 Suppression auto du dossier parent si nom identique
- 💾 Cache SQLite avec batch commits
- ⚡ Multi-threading (auto: CPU threads par défaut)
- 📊 Barre de progression avec ETA et threads
- 🔍 Mode dry-run (simulation)
- 💬 Mode verbose avec queue thread-safe
- ⚠️ Confirmation manuelle par défaut
- 🚀 Option 'a' pour tout supprimer (yes to all)
- ⏸️ Pause validation après détection

## 📊 Options

| Option | Description | Défaut |
|--------|-------------|--------|
| `-S, --source` | Répertoire source | Requis |
| `-D, --dest` | Destination (répétable) | Requis |
| `--cache` | Fichier cache SQLite | `media_cache.db` |
| `--workers` | Threads pour hash | `auto` (CPU) |
| `--dry-run` | Simulation sans suppression | `False` |
| `--auto-delete` | Sans confirmation ⚠️ | `False` |
| `--clear-cache` | Vider le cache | `False` |
| `-v, --verbose` | Affiche actions en temps réel | `False` |

## 💡 Exemples de sortie

```
🧹 ORPHAN FILE SWEEPER
============================================================
📂 Source: /mnt/data/torrents
🎯 Destinations: 1 répertoire(s)
   • /mnt/data/media

🔗 Sous-dossiers matchés avec media: 4k, movies, shows

🔍 ANALYSE DES FICHIERS
============================================================
📁 Scan: /mnt/data/torrents/movies
   Source: 2194 fichiers
📁 Scan: /mnt/data/media/movies
   Destination: 2560 fichiers

📊 Total destinations: 2560 fichiers
⚡ Filtre rapide: 311 candidats orphelins

🔐 Calcul hash pour 311 candidats...
   ⏳ Progression: 311/311 (100.0%) | ⚡ 589.1 fichiers/s | 💻 16/16 threads | ⏱️  ETA: 0s

🔐 Calcul hash pour 160 destinations...
   ⏳ Progression: 160/160 (100.0%) | ⚡ 11112.5 fichiers/s | 💻 16/16 threads | ⏱️  ETA: 0s

⏸️  30 orphelin(s) détectés. Appuyez sur Entrée pour continuer...

⚠️  30 FICHIER(S) ORPHELIN(S) DÉTECTÉ(S)
============================================================
💾 Taille totale: 245.00 GB (245.00 GB)
⏱️  Durée du scan: 12.3s

────────────────────────────────────────────────────────────
🗑️  FICHIER ORPHELIN DÉTECTÉ
────────────────────────────────────────────────────────────
📄 Fichier: Jurassic.World.Rebirth.2025.mkv
📂 Chemin: /mnt/data/torrents/movies/Jurassic.World.Rebirth.2025
💾 Taille: 8,589,934,592 bytes (8192.00 MB)
📅 Date: 2025-01-15 14:23:45

⚠️  Ce fichier n'existe dans aucune destination.

❓ Supprimer ce fichier? ([O]ui/n/a/q): o
   ✅ Supprimé: Jurassic.World.Rebirth.2025.mkv
   ✅ Dossier supprimé: Jurassic.World.Rebirth.2025/
```

## 💡 Options de confirmation

Lors de la suppression, vous pouvez répondre :
- **o** (oui) : Supprimer ce fichier
- **n** (non) : Ignorer ce fichier
- **a** (all/tout) : Supprimer tous les fichiers restants sans demander
- **q** (quitter) : Abandonner l'opération

## ⚡ Performances

### Optimisations automatiques

- Buffer 1MB pour lecture fichiers (16x moins d'appels système)
- Threads auto = nombre de CPU (I/O bound)
- Cache SQLite avec batch commits
- Filtre rapide par taille+mtime (~90% fichiers évités)

### Ajustement selon stockage

```bash
# Disque local SSD/NVMe (défaut optimal)
python3 orphan_sweeper.py -S /source -D /dest

# NAS/réseau (augmenter threads pour compenser latence)
python3 orphan_sweeper.py -S /nas/source -D /nas/dest --workers 32

# HDD mécanique lent (réduire threads)
python3 orphan_sweeper.py -S /source -D /dest --workers 8
```

### Vitesse attendue

- SSD local : 50-100 fichiers/s
- NAS gigabit : 5-20 fichiers/s
- HDD mécanique : 10-30 fichiers/s

## 📄 Licence

Code généré par **Amazon Q Developer** (AWS).

**Utilisation à vos risques et périls** - Aucune responsabilité pour pertes de données.
