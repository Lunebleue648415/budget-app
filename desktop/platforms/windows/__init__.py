"""Ce qui est propre à Windows. Cf. platforms/__init__.py pour l'interface.

Rien ici n'est indispensable au fonctionnement de l'application : sans ce
module, elle démarrerait et fonctionnerait à l'identique — la fenêtre serait
simplement regroupée sous l'icône générique de Python dans la barre des
tâches, et une erreur fatale ne s'écrirait que dans le journal. D'où les
`except` larges : une API native indisponible ne doit jamais empêcher de
lancer un gestionnaire de budget.
"""
import ctypes

NOM = "Windows"

# .ico et non .png : c'est le seul format qu'accepte PyInstaller pour l'icône
# d'un exécutable Windows, et le seul que l'Explorateur sait afficher à toutes
# les tailles (il contient les six variantes, de 16 à 256 px).
FICHIER_ICONE = "icone.ico"

# Identifiant d'application Windows (AppUserModelID). Sans lui, Windows
# regroupe la fenêtre sous l'icône générique de l'interpréteur Python : elle
# n'a alors ni sa propre entrée dans la barre des tâches, ni son icône, et ne
# peut pas être épinglée. Convention Microsoft : Société.Produit.
APP_USER_MODEL_ID = "FelipeGarcia.BudgetApp"


def identite_application() -> None:
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass  # purement cosmétique : jamais une raison d'empêcher le démarrage


def afficher_erreur(titre: str, message: str) -> bool:
    """Boîte de dialogue modale native (MessageBoxW).

    0x10 = MB_ICONERROR : l'icône rouge dit d'un coup d'œil que l'application
    n'a pas démarré, là où une fenêtre sans icône passerait pour un simple
    avertissement."""
    try:
        ctypes.windll.user32.MessageBoxW(None, message, titre, 0x10)
        return True
    except Exception:
        return False


# Configuration lue par .NET Framework au chargement du processus. Son nom doit
# rester CALÉ SUR CELUI DE L'EXÉCUTABLE (« Budget App.exe » -> « Budget
# App.exe.config ») : c'est par cette convention que .NET la trouve. Renommer
# l'application impose donc de renommer ce fichier, faute de quoi il cesse
# silencieusement d'être lu — et l'application recommence à mourir au démarrage
# après un téléchargement. Le pourquoi est écrit en toutes lettres dedans.
FICHIER_CONFIG_NET = "Budget App.exe.config"


def options_pyinstaller() -> dict:
    """Options passées à EXE() par budget_app.spec.

    `console=False` : l'application est fenêtrée, une console noire s'ouvrirait
    derrière elle à chaque lancement. C'est aussi ce qui rend `afficher_erreur`
    indispensable — sans console, un échec au démarrage serait muet."""
    return {
        "console": False,
        # Aucun bundle à part sur Windows : le dossier produit par COLLECT est
        # directement l'application (« Budget App\Budget App.exe »).
        "bundle": None,
        # Copiés tels quels À CÔTÉ de l'exécutable, depuis le dossier de cette
        # plateforme. Windows est le seul à en avoir besoin (cf.
        # FICHIER_CONFIG_NET) ; les deux autres rendent une liste vide.
        "fichiers_racine": [FICHIER_CONFIG_NET],
    }
