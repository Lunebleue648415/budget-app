"""Le seul réglage que l'application mémorise D'UN LANCEMENT À L'AUTRE : où est
la base de données de l'utilisateur.

POURQUOI PAS À CÔTÉ DE L'EXÉCUTABLE, comme tout le reste (`data/`,
`extensions/`, `extensions.json`). Parce que ce fichier-ci existe précisément
pour survivre à ce qui efface ce dossier. Mettre à jour l'application, c'est
décompresser une nouvelle archive par-dessus l'ancienne — ou, sur macOS,
remplacer le bundle `.app` en entier, ce que le Finder fait sans jamais
proposer de fusionner. Un pointeur rangé là disparaîtrait avec la mise à jour,
l'application retomberait sur son emplacement par défaut, y créerait une base
VIDE, et l'utilisateur conclurait qu'il a tout perdu — alors que ses données
sont intactes, quelque part, sans que rien ne sache plus où.

D'où l'emplacement de configuration prévu par chaque système, qu'aucune
installation ni désinstallation d'application ne touche.

CE FICHIER NE CONTIENT QUE DES CHEMINS, jamais de données financières : perdu
ou supprimé, on retombe sur le premier démarrage, qui redemande où ranger la
base. C'est une gêne, pas une perte.

RIEN N'Y LÈVE JAMAIS. Un dossier en lecture seule, un JSON abîmé à la main, un
profil utilisateur biscornu : dans tous ces cas l'application doit démarrer, et
se comporter comme au premier lancement. Une exception ici tuerait le
processus avant même que la fenêtre s'ouvre (cf. desktop/app_desktop.py, où
tout ce qui précède `webview.start()` est fatal).
"""
import json
import os
import sys
from pathlib import Path

NOM_APPLICATION = "Budget App"
_NOM_FICHIER = "config.json"

# La clé du chemin de base dans le fichier. Nommée plutôt qu'écrite en dur aux
# trois endroits qui la lisent : renommer un jour reste alors une seule ligne.
CLE_CHEMIN_BASE = "chemin_base"


def dossier_config() -> Path:
    """Le dossier de configuration de l'utilisateur, selon les conventions du
    système. Il n'est PAS créé ici — seule une écriture le crée, et une
    application qu'on n'a jamais configurée n'a aucune raison de laisser une
    trace dans le profil.

    BUDGET_CONFIG_DIR le détourne, pour la même raison que BUDGET_DB_PATH
    détourne la base : un test ou un bac à sable ne doit pas écrire dans la
    configuration réelle de la machine qui l'exécute — il y écrirait un chemin
    de base temporaire que l'application relirait au prochain démarrage."""
    detourne = os.environ.get("BUDGET_CONFIG_DIR")
    if detourne:
        return Path(detourne).expanduser()
    if sys.platform == "win32":
        # LOCALAPPDATA et non APPDATA : le chemin d'une base locale n'a aucun
        # sens à être synchronisé d'une machine à l'autre par un profil
        # itinérant — il désignerait un fichier qui n'existe pas en face.
        racine = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        base = Path(racine) if racine else Path.home() / "AppData" / "Local"
        return base / NOM_APPLICATION
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / NOM_APPLICATION
    # Linux et le reste : la spécification XDG, dont la valeur par défaut est
    # ~/.config quand la variable n'est pas posée.
    racine = os.environ.get("XDG_CONFIG_HOME")
    base = Path(racine) if racine else Path.home() / ".config"
    return base / "budget-app"


def fichier_config() -> Path:
    return dossier_config() / _NOM_FICHIER


def lire() -> dict:
    """Le contenu du fichier, ou un dictionnaire vide — jamais d'exception.

    Un JSON abîmé rend un dictionnaire vide plutôt qu'une erreur : le pire
    service à rendre à quelqu'un dont le fichier de configuration est corrompu
    serait de l'empêcher d'ouvrir l'application pour le réparer."""
    try:
        contenu = json.loads(fichier_config().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return contenu if isinstance(contenu, dict) else {}


def ecrire(**valeurs) -> bool:
    """Fusionne `valeurs` dans le fichier. Rend False si rien n'a pu être
    écrit (dossier en lecture seule, disque plein) — l'appelant le dit alors à
    l'utilisateur, dont le choix ne vaudra que pour cette session."""
    contenu = lire()
    contenu.update(valeurs)
    try:
        dossier_config().mkdir(parents=True, exist_ok=True)
        fichier_config().write_text(
            json.dumps(contenu, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return True
    except OSError:
        return False


def chemin_base_memorise() -> Path | None:
    """Le chemin retenu au dernier choix de l'utilisateur, ou None.

    LE FICHIER N'EST PAS VÉRIFIÉ ICI. Qu'il ait disparu (disque externe
    débranché, dossier renommé) est une information à porter à l'écran, pas à
    avaler en silence en retombant sur la base par défaut : retomber
    donnerait une application vide, sans un mot, exactement le scénario que
    tout ceci existe pour éviter."""
    valeur = lire().get(CLE_CHEMIN_BASE)
    if not isinstance(valeur, str) or not valeur.strip():
        return None
    try:
        return Path(valeur).expanduser()
    except (OSError, ValueError):
        return None


def oublier_chemin_base() -> bool:
    """Retire le chemin mémorisé : l'application repartira sur son emplacement
    par défaut, et redemandera où ranger la base au prochain lancement."""
    contenu = lire()
    contenu.pop(CLE_CHEMIN_BASE, None)
    try:
        dossier_config().mkdir(parents=True, exist_ok=True)
        fichier_config().write_text(
            json.dumps(contenu, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return True
    except OSError:
        return False
