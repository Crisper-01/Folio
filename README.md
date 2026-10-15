# Folio

Éditeur PDF **100 % local** pour Windows et Linux. Vos documents ne quittent jamais votre ordinateur.

## Fonctionnalités

**Pages**
- Miniatures avec glisser-déposer pour réordonner (sélection multiple)
- Insérer une page vierge, un autre PDF ou des images (glisser des fichiers sur les miniatures)
- Pivoter, dupliquer, supprimer, monter/descendre
- Extraire des pages, scinder le document (toutes les N pages ou par plages), fusionner des PDF

**Annotations** (modifiables jusqu'à l'enregistrement, puis intégrées au PDF)
- Texte : polices sans/serif/mono et 9 polices calligraphiques, taille, gras, italique, alignement, couleur, opacité
- Signature : dessin à main levée, nom écrit dans une police calligraphiée, ou image importée (fond blanc rendu transparent). Les signatures sont mémorisées pour être réutilisées.
- Dessin libre, surligneur, rectangle, ellipse, ligne, flèche, image
- Caviardage : à l'enregistrement, le texte et les images sous la zone sont réellement supprimés
- Déplacement, redimensionnement par poignées, rotation, premier plan/arrière-plan, duplication

**Outils**
- Compression avec 3 niveaux ou réglages personnalisés, estimation de la taille avant d'enregistrer, niveaux de gris, suppression des métadonnées
- Filigrane texte ou image, centré ou en mosaïque, angle et opacité réglables, sur tout ou partie des pages (retirable)
- Images vers PDF (JPG, PNG, WebP, TIFF...) : ordre des images, format A4/Lettre/taille de l'image, marges, et filigrane optionnel dès la conversion
- Numérotation des pages (format, position, première page exclue...)
- Protection par mot de passe (AES-256) et permissions ; ouverture des PDF protégés
- Recherche dans le texte, export des pages en PNG/JPEG, impression, métadonnées
- Annuler/rétablir illimité, thème clair/sombre (ou suivant le système), signets conservés

## Installation

**Windows** : décompressez `folio-<version>-windows-x64.zip` et lancez `Folio\Folio.exe`.

**Linux** (Ubuntu 20.04+, Debian 10+, Fedora, RHEL 8+...) :

```bash
tar xzf folio-<version>-linux-x86_64.tar.gz
./folio-<version>-linux-x86_64/install.sh   # installe dans ~/.local, sans sudo
folio
```

## Raccourcis

| Action | Raccourci |
|---|---|
| Sélection / Texte / Dessin / Surligner | V / T / P / H |
| Rectangle / Ellipse / Ligne / Flèche / Caviarder | R / E / L / A / X |
| Annuler / Rétablir | Ctrl+Z / Ctrl+Y |
| Rechercher | Ctrl+F |
| Zoom | Ctrl+molette, Ctrl+plus/moins, Ctrl+0 / Ctrl+1 / Ctrl+2 |
| Déplacer la vue | Espace + glisser, ou clic molette |
| Contraindre (carré, 45°, proportions) | Maj pendant le tracé |

## Développement

Python 3.11+ :

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"     # Linux : .venv/bin/pip
python -m folio [fichier.pdf]
python -m pytest                        # tests moteur + interface (Qt offscreen)
ruff check . && ruff format --check .
```

Captures d'écran de bout en bout (pilotage de la vraie interface) :

```bash
python e2e/sample.py /tmp/contrat.pdf
FOLIO_THEME=dark python e2e/shot.py /tmp/shots /tmp/contrat.pdf basic   # scénarios : basic, edit, pages, dialogs
```

### Construire les exécutables

- Windows : `powershell scripts/build_windows.ps1`, produit `dist/folio-<version>-windows-x64.zip`
- Linux, depuis n'importe quel OS avec Docker : `bash scripts/build_linux_docker.sh`, produit `dist-linux/folio-<version>-linux-x86_64.tar.gz` (construit sur AlmaLinux 8 pour une compatibilité glibc 2.28+)

Chaque build lance les tests puis `Folio --selftest` (polices, rendu, export, compression dans le processus de travail).

### Architecture

- `folio/model.py` : document = liste de références de pages vers des PDF sources gardés intacts en mémoire. Les opérations sur les pages et l'annulation sont donc instantanées.
- `folio/overlays.py` : annotations éditables, exprimées dans l'espace non pivoté de la page.
- `folio/export.py` : assemble le PDF final et y grave les annotations (PyMuPDF), compression.
- `folio/stamps.py` : filigranes, numérotation, images vers PDF (annotations générées en groupe).
- `folio/ui/` : interface PySide6. `paint.py` dessine les annotations avec les mêmes polices et métriques que l'export, pour que l'écran corresponde exactement au PDF.

Licences : PyMuPDF (AGPL), Qt/PySide6 (LGPL), polices OFL/Apache, icônes Lucide (ISC).
