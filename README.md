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

### Algorithme

```
1. SCAN
   └─> Collecte métadonnées (taille, mtime)

2. FILTRE RAPIDE
   └─> Élimine fichiers identiques (taille + mtime)
   └─> Économie : ~90% des calculs hash

3. HASH MD5
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
- 🔐 Hash MD5 avec cache SQLite indexé
- ⚡ Multi-threading (auto: CPU threads par défaut)
- 📊 Barre de progression avec ETA
- 🔍 Mode dry-run (simulation)
- ⚠️ Confirmation manuelle par défaut
- 🚀 Option 'a' pour tout supprimer (yes to all)

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
📂 Source: test/source
🎯 Destinations: 2 répertoire(s)

🔍 ANALYSE DES FICHIERS
============================================================
   Source: 50 fichiers
   Destination: 40 fichiers
   Destination: 30 fichiers

📊 Total destinations: 70 fichiers
⚡ Filtre rapide: 15 candidats orphelins

🔐 Calcul hash pour 15 candidats (20/16 threads)...
   ⏳ Progression: 15/15 (100.0%) | ⚡ 85.3 fichiers/s | ⏱️  ETA: 12min

⚠️  15 FICHIER(S) ORPHELIN(S) DÉTECTÉ(S)
============================================================
💾 Taille totale: 245.00 MB (0.24 GB)
⏱️  Durée du scan: 0.8s

────────────────────────────────────────────────────────────
🗑️  FICHIER ORPHELIN DÉTECTÉ
────────────────────────────────────────────────────────────
📄 Fichier: old_movie.mp4
📂 Chemin: test/source
💾 Taille: 16,777,216 bytes (16.00 MB)
📅 Date: 2025-10-31 11:31:29

⚠️  Ce fichier n'existe dans aucune destination.

❓ Supprimer ce fichier? ([O]ui/n/a/q): 
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
