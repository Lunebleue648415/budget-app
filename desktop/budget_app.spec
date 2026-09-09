# Spec PyInstaller de Budget App — GÉNÉRIQUE AUX TROIS SYSTÈMES.
#
# Construction (depuis la racine du dépôt) :
#     Windows : backend\.venv\Scripts\python.exe -m PyInstaller desktop\budget_app.spec --noconfirm
#     Linux   : backend/.venv/bin/python -m PyInstaller desktop/budget_app.spec --noconfirm
#     macOS   : idem Linux
#
# Résultat : desktop/dist/Budget App/ (Windows, Linux) ou
#            desktop/dist/Budget App.app/ (macOS, cf. BUNDLE plus bas).
# Le dossier doit rester dans un emplacement accessible en écriture (pas
# "Program Files") : la base de test est créée à côté de l'exécutable.
#
# CE QUI CHANGE D'UN SYSTÈME À L'AUTRE N'EST PAS ÉCRIT ICI, mais dans
# desktop/platforms/<systeme>/ : format d'icône, options d'EXE, bundle macOS.
# Cette spec ne fait que les lire (`platforms.options_pyinstaller()`), pour
# qu'ajouter un système ne demande jamais d'y toucher — c'est tout l'objet de
# la séparation générique / spécifique.
import sys
from pathlib import Path

# __file__ n'existe pas dans une spec exécutée par PyInstaller : SPECPATH est
# fourni par PyInstaller et pointe sur le dossier de ce fichier.
DOSSIER_DESKTOP = Path(SPECPATH).resolve()
RACINE = DOSSIER_DESKTOP.parent
BACKEND = RACINE / "backend"

# `platforms` vit à côté de cette spec, qui n'est pas exécutée depuis son
# propre dossier : sans cet ajout, l'import échouerait.
sys.path.insert(0, str(DOSSIER_DESKTOP))
import platforms  # noqa: E402  (l'ajout au sys.path ci-dessus doit le précéder)

OPTIONS = platforms.options_pyinstaller()
ICONE = platforms.CHEMIN_ICONE

# Données embarquées, communes aux trois systèmes.
donnees = [
    # Frontend servi tel quel par FastAPI (cf. main.py::_dossier_frontend).
    (str(RACINE / "frontend"), "frontend"),
    # Migrations : alembic lit env.py et versions/*.py comme des fichiers
    # source à l'exécution, ils doivent donc rester des données du bundle
    # et non être compilés dans l'archive.
    (str(BACKEND / "alembic"), "alembic"),
]

# LES EXTENSIONS NE SONT PAS EMBARQUÉES, et c'est délibéré. L'application est
# livrée sans aucune : l'utilisateur télécharge celles qu'il veut et les dépose
# dans le dossier `extensions/` créé À CÔTÉ de l'exécutable au premier
# lancement (cf. app/extensions.py::preparer_dossiers).
#
# Les embarquer ici les extrairait sous sys._MEIPASS, un dossier temporaire
# recréé à chaque lancement : elles y seraient en lecture seule, invisibles
# pour l'utilisateur, et impossibles à compléter par les siennes. Le dossier
# livré doit donc rester vide, y compris pour la version développeur —
# `extensions-dev/` ne part jamais dans un binaire.

# Linux n'incruste pas d'icône dans le binaire (le format ELF n'a pas de
# section pour ça) : elle est copiée à côté et référencée par le .desktop.
if not OPTIONS.get("icone_incrustee", True):
    donnees.append((str(ICONE), "."))


a = Analysis(
    [str(DOSSIER_DESKTOP / "app_desktop.py")],
    pathex=[str(BACKEND), str(DOSSIER_DESKTOP)],  # `app` et `platforms` importables à l'analyse
    binaries=[],
    datas=donnees,
    hiddenimports=[
        # Importés dynamiquement par uvicorn/alembic : invisibles à l'analyse statique.
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        "app.models",
        "app.routers",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tkinter"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Budget App",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=OPTIONS["console"],
    disable_windowed_traceback=False,
    argv_emulation=OPTIONS.get("argv_emulation", False),
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # None sous Linux : PyInstaller ignore alors l'option au lieu d'échouer sur
    # un format qu'il ne sait pas incruster.
    icon=str(ICONE) if OPTIONS.get("icone_incrustee", True) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Budget App",
)

# FICHIERS POSÉS À CÔTÉ DE L'EXÉCUTABLE, APRÈS COLLECT.
#
# PAS via `datas` : depuis PyInstaller 6, tout ce qui y passe atterrit dans le
# sous-dossier `_internal/`, et la racine du dossier livré ne contient plus que
# l'exécutable. Or ces fichiers-là ne valent QUE s'ils sont à côté de lui —
# c'est le cas de « Budget App.exe.config », que .NET Framework cherche sous le
# nom exact de l'exécutable et nulle part ailleurs (vérifié : dans `_internal/`,
# il est ignoré et l'application meurt au démarrage après un téléchargement).
#
# ICI ET NON DANS LES SCRIPTS DE BUILD : il y en a deux (construire.ps1 en
# local, le workflow GitHub en CI), et un fichier oublié dans l'un des deux ne
# se verrait que sur les bundles produits par celui-là. La spec est le seul
# endroit que les deux traversent.
if OPTIONS.get("fichiers_racine"):
    import shutil

    racine_livree = Path(DISTPATH) / "Budget App"
    racine_livree.mkdir(parents=True, exist_ok=True)
    for nom_fichier in OPTIONS["fichiers_racine"]:
        shutil.copy2(platforms.DOSSIER_PLATEFORME / nom_fichier, racine_livree / nom_fichier)

# macOS seulement : le Finder ne lance pas un exécutable nu, il lance un
# bundle .app — un dossier à structure imposée que PyInstaller construit à
# partir du COLLECT ci-dessus. Les deux autres systèmes n'ont rien à faire ici.
if OPTIONS.get("bundle"):
    app = BUNDLE(
        coll,
        name=OPTIONS["bundle"]["name"],
        icon=str(ICONE),
        bundle_identifier=OPTIONS["bundle"]["bundle_identifier"],
        info_plist=OPTIONS["bundle"]["info_plist"],
    )
