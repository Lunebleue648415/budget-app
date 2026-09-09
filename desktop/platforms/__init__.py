"""Ce que Budget App fait DIFFÉREMMENT selon le système d'exploitation.

TOUT LE RESTE EST GÉNÉRIQUE. Le backend (FastAPI, SQLAlchemy, Alembic), le
frontend et le lanceur `app_desktop.py` tournent tels quels sur les trois
systèmes : ils ne manipulent que des `pathlib.Path` et n'appellent aucune API
native. Ce paquet isole les rares endroits où le système impose sa propre
façon de faire — trois choses, pas une de plus :

1. L'IDENTITÉ DE L'APPLICATION auprès du gestionnaire de fenêtres (barre des
   tâches Windows, dock macOS, barre de lancement Linux) ;
2. LE SIGNALEMENT D'UNE ERREUR FATALE, quand la fenêtre n'a pas pu s'ouvrir :
   il n'y a alors ni console ni interface pour le dire, et chaque système a sa
   propre boîte de dialogue native ;
3. L'EMPAQUETAGE : format d'icône (.ico / .png / .icns) et options PyInstaller
   propres au système.

CHAQUE MODULE DE PLATEFORME EXPOSE LA MÊME INTERFACE, et c'est ce qui permet à
`app_desktop.py` de ne jamais tester `sys.platform` lui-même :

    NOM                       -> str, nom lisible du système
    FICHIER_ICONE             -> str, nom du fichier icône dans son dossier
    identite_application()    -> None, jamais bloquant
    afficher_erreur(t, m)     -> bool, True si une boîte native a pu s'ouvrir
    options_pyinstaller()     -> dict, fusionné dans budget_app.spec

Ce module y ajoute DOSSIER_PLATEFORME et CHEMIN_ICONE, résolus depuis le module
retenu : chaque plateforme range chez elle ce qui lui appartient (son icône, et
sous Windows la configuration .NET livrée à côté de l'exécutable — clé
`fichiers_racine` des options), et la spec n'a donc jamais à reconstruire ces
chemins à la main.

POURQUOI DES IMPORTS STATIQUES ET NON `importlib`. PyInstaller analyse le code
SANS L'EXÉCUTER : un `importlib.import_module(f"platforms.{nom}")` ne lui dirait
rien, et le module de plateforme serait absent du bundle — l'application
échouerait au démarrage, sur la machine de l'utilisateur uniquement. Les trois
`import` ci-dessous sont donc volontairement écrits en clair.
"""
import sys
from pathlib import Path


def _charger():
    """Le module correspondant au système courant.

    Linux est le repli par défaut plutôt qu'une erreur : les BSD et les autres
    UNIX se comportent comme lui pour les trois points ci-dessus (aucune API
    native n'y est appelée), et refuser de démarrer sur un système simplement
    inconnu serait plus brutal que juste."""
    if sys.platform == "win32":
        from . import windows

        return windows
    if sys.platform == "darwin":
        from . import macos

        return macos
    from . import linux

    return linux


plateforme = _charger()

NOM = plateforme.NOM
FICHIER_ICONE = plateforme.FICHIER_ICONE
identite_application = plateforme.identite_application
afficher_erreur = plateforme.afficher_erreur
options_pyinstaller = plateforme.options_pyinstaller

# L'icône est rangée dans le dossier de sa plateforme : `__file__` du module
# retenu la localise sans que personne ait à réécrire « platforms/<nom>/ ».
DOSSIER_PLATEFORME = Path(plateforme.__file__).resolve().parent
CHEMIN_ICONE = DOSSIER_PLATEFORME / FICHIER_ICONE
