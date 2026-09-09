"""Point d'entrée de Budget App en application de bureau. GÉNÉRIQUE : ce
module tourne tel quel sur Windows, Linux et macOS.

L'application reste le même serveur FastAPI qu'en développement : il n'est
simplement plus lancé à la main et plus consulté dans un navigateur. Ce
module l'enveloppe pour en faire une application de bureau classique :

1. applique les migrations Alembic sur la base ciblée (premier lancement =
   schéma créé, nouvelle version de l'app = schéma mis à jour) ;
2. démarre uvicorn sur 127.0.0.1, sur un port attribué par le système, dans
   un thread démon — aucun conflit possible avec un port déjà occupé ;
3. ouvre une fenêtre native (pywebview / Edge WebView2) sur ce serveur.

Fermer la fenêtre termine le processus : le serveur vivant dans un thread
démon s'arrête avec lui.

La base utilisée est celle que résout `app.database` (base de test à côté de
l'exécutable en mode packagé, cf. `_dossier_donnees_par_defaut`), ou celle
désignée par BUDGET_DB_PATH. La base personnelle, elle, ne se rejoint qu'en
saisissant son chemin dans le panneau "Base de données" de l'application —
elle n'est jamais mémorisée ni découverte automatiquement.

AUCUN TEST DE SYSTÈME ICI. Les trois seuls comportements qui diffèrent d'un
système à l'autre (identité auprès du gestionnaire de fenêtres, boîte
d'erreur native, empaquetage) vivent dans `platforms/`, qui expose la même
interface partout — cf. son en-tête. Ce module n'a donc jamais à savoir sur
quoi il tourne.

RIEN NE SORT DE LA MACHINE. Le serveur écoute sur 127.0.0.1 (boucle locale,
inaccessible depuis le réseau) sur un port attribué par le système, et la
seule requête émise ici est le health-check de l'application sur elle-même.
"""
import socket
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

import platforms

TITRE = "Budget App"


def _est_packagee() -> bool:
    return getattr(sys, "frozen", False)


def _racine_ressources() -> Path:
    """Dossier où trouver les ressources embarquées (alembic, frontend) : le
    bundle extrait en mode packagé, le dossier `backend/` du repo sinon."""
    if _est_packagee():
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[1] / "backend"


def _preparer_import_backend() -> None:
    """En développement, `backend/` n'est pas sur le sys.path (ce script vit
    dans `desktop/`) : on l'ajoute pour pouvoir importer le paquet `app`. En
    mode packagé, `app` est déjà embarqué dans l'exécutable."""
    if not _est_packagee():
        sys.path.insert(0, str(_racine_ressources()))


def _appliquer_migrations() -> Path | None:
    """Amène la base au schéma de cette version. Rend le chemin de la copie de
    sécurité prise avant migration, ou None si rien n'a eu à changer.

    `alembic upgrade head` par l'API Python plutôt que la ligne de commande. La
    configuration est construite en mémoire, sans alembic.ini : l'URL de base
    est de toute façon imposée par `alembic/env.py`, qui la relit depuis
    `app.database` (donc la même que celle de l'application).

    UNE COPIE EST PRISE AVANT DE TOUCHER À UNE BASE QUI EXISTE DÉJÀ. Ce
    démarrage-ci ne migre plus une base de test jetable posée à côté de
    l'exécutable : depuis que l'emplacement est choisi par l'utilisateur (cf.
    app/database.py), il migre SA base, celle qu'il a rangée dans ses
    documents. Une migration réussie ne perd rien — mais c'est précisément le
    moment où l'on regrette de ne pas avoir de copie, puisque le schéma change
    sous des données qu'on ne peut pas reconstituer.

    UNE BASE QUI N'EXISTE PAS ENCORE passe au contraire par l'`upgrade` nu :
    il n'y a rien à sauvegarder, et c'est lui qui CRÉE le fichier, y pose le
    schéma et son contenu initial. C'est le tout premier lancement.
    """
    from alembic import command
    from alembic.config import Config

    from app import database

    cible = database.DATABASE_PATH
    if cible.is_file() and database.revision_actuelle(cible) is not None:
        sauvegarde, _revision_quittee = database.migrer_si_necessaire(cible)
        return sauvegarde

    config = Config()
    config.set_main_option("script_location", str(_racine_ressources() / "alembic"))
    command.upgrade(config, "head")
    return None


def _socket_local() -> tuple[socket.socket, int]:
    """Réserve un port libre en le faisant choisir par le système. Le socket
    déjà lié est ensuite passé tel quel à uvicorn : aucune fenêtre entre la
    réservation et l'écoute, donc aucun risque que le port soit pris entre
    les deux."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    return sock, sock.getsockname()[1]


def _demarrer_serveur(sock: socket.socket) -> list[str]:
    """Démarre uvicorn dans un thread démon et renvoie une liste qui recevra
    la trace d'une éventuelle erreur du serveur.

    Sans ce relais, une exception levée dans le thread serait totalement
    silencieuse : l'attente de /health échouerait sans jamais dire pourquoi.
    """
    import uvicorn

    from app.main import app

    # log_config=None : en mode fenêtré, stdout/stderr n'existent pas et la
    # configuration de journalisation par défaut d'uvicorn écrirait dessus.
    serveur = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False))
    erreurs: list[str] = []

    def executer() -> None:
        try:
            serveur.run(sockets=[sock])
        except Exception:
            erreurs.append(traceback.format_exc())

    threading.Thread(target=executer, daemon=True).start()
    return erreurs


def _attendre_serveur(url_sante: str, delai_max: float = 30.0) -> bool:
    limite = time.monotonic() + delai_max
    while time.monotonic() < limite:
        try:
            with urllib.request.urlopen(url_sante, timeout=1) as reponse:
                if reponse.status == 200:
                    return True
        except (urllib.error.URLError, OSError, TimeoutError):
            time.sleep(0.05)
    return False


def _signaler_erreur(message: str) -> None:
    """En mode fenêtré il n'y a ni console ni terminal : sans ça, un échec au
    démarrage serait totalement silencieux. Le détail complet part aussi dans
    un fichier à côté de la base, pour pouvoir diagnostiquer après coup.

    La boîte native est déléguée à la plateforme, qui rend False quand elle
    n'a pas pu en ouvrir une (aucun utilitaire de dialogue sous Linux, session
    sans bureau) : stderr reste alors le dernier recours — inutile dans une
    application fenêtrée, mais lisible pour qui l'a lancée d'un terminal."""
    try:
        from app.database import DEV_DB_PATH

        journal = DEV_DB_PATH.parent / "erreur.log"
        journal.write_text(message, encoding="utf-8")
        message = f"{message}\n\nDétail enregistré dans :\n{journal}"
    except Exception:
        pass

    if not platforms.afficher_erreur(f"{TITRE} — erreur", message):
        print(message, file=sys.stderr)


class ApiBureau:
    """Le peu de NATIF que la page ne peut pas faire seule, exposé au JavaScript.

    POURQUOI ÇA EXISTE. Un navigateur ne donne JAMAIS le chemin complet d'un
    fichier choisi par l'utilisateur — c'est une limite de sécurité, pas un
    oubli : `<input type="file">` ne rend qu'un nom. Or l'application demande
    précisément un chemin complet, et le seul écran qui le demande est celui du
    premier démarrage, devant quelqu'un qui vient d'installer l'application et
    n'a aucune raison de savoir écrire `C:\\Users\\...\\Documents\\...` à la
    main. La fenêtre de bureau, elle, peut ouvrir le sélecteur du SYSTÈME.

    pywebview expose ces méthodes sous `window.pywebview.api.<nom>`, en
    promesses. Elles n'existent QUE dans l'application de bureau : ouvert dans
    un navigateur pendant le développement, `window.pywebview` est absent, et
    l'écran retombe sur la saisie à la main (cf. app.js).
    """

    def choisir_emplacement_base(self, chemin_propose: str = "") -> str | None:
        """Sélecteur « enregistrer sous » : il accepte un fichier qui n'existe
        pas encore, ce qui est le cas normal ici — on choisit OÙ RANGER une base
        qui sera créée ou déplacée là. Un sélecteur d'ouverture ne saurait
        désigner que des fichiers déjà présents.

        Rend None quand l'utilisateur annule ; l'écran laisse alors le champ
        tel quel plutôt que de l'effacer."""
        return self._dialogue("enregistrer", chemin_propose)

    def choisir_base_existante(self, chemin_propose: str = "") -> str | None:
        """Sélecteur d'ouverture, pour le panneau des Paramètres : là, on
        rejoint une base qui existe déjà (celle qu'on retrouve après une mise à
        jour, celle d'un disque externe)."""
        return self._dialogue(
            "ouvrir",
            chemin_propose,
            file_types=("Base de données (*.db;*.sqlite;*.sqlite3)", "Tous les fichiers (*.*)"),
        )

    def _dialogue(self, mode: str, chemin_propose: str, file_types=()) -> str | None:
        # Importé ICI et pas en tête de module : `webview` tire les
        # bibliothèques graphiques du système, et tout ce qui précède
        # l'ouverture de la fenêtre (migrations, serveur) doit pouvoir tourner
        # sans elles — c'est la règle que suit déjà `main()`.
        import webview

        depart = Path(chemin_propose) if chemin_propose else None
        try:
            resultat = webview.windows[0].create_file_dialog(
                webview.SAVE_DIALOG if mode == "enregistrer" else webview.OPEN_DIALOG,
                # Le dossier proposé, pour ouvrir le sélecteur AU BON ENDROIT
                # plutôt qu'à la racine du disque. Seulement s'il existe : un
                # dossier inventé y ferait échouer l'ouverture sur certaines
                # plateformes.
                directory=str(depart.parent) if depart and depart.parent.is_dir() else "",
                save_filename=depart.name if depart else "",
                file_types=file_types,
            )
        except Exception:
            # Un sélecteur qui ne s'ouvre pas ne doit pas casser l'écran : la
            # saisie à la main reste possible, et c'était le seul chemin avant.
            return None
        if not resultat:
            return None
        # SAVE_DIALOG rend une chaîne, les autres une séquence : les deux
        # existent selon la plateforme et la version, on ne parie pas.
        return resultat if isinstance(resultat, str) else resultat[0]


def main() -> int:
    platforms.identite_application()
    _preparer_import_backend()

    try:
        _appliquer_migrations()
    except Exception:
        _signaler_erreur(
            "Impossible de préparer la base de données.\n\n" + traceback.format_exc()
        )
        return 1

    sock, port = _socket_local()
    url = f"http://127.0.0.1:{port}"
    try:
        erreurs_serveur = _demarrer_serveur(sock)
    except Exception:
        _signaler_erreur("Impossible de démarrer le serveur local.\n\n" + traceback.format_exc())
        return 1

    if not _attendre_serveur(f"{url}/health"):
        detail = erreurs_serveur[0] if erreurs_serveur else "Aucune erreur remontée par le serveur."
        _signaler_erreur("Le serveur local n'a pas répondu dans le temps imparti.\n\n" + detail)
        return 1

    import webview

    # `text_select=True` : SANS LUI, RIEN N'EST SÉLECTIONNABLE dans l'application
    # de bureau. pywebview injecte par défaut `body { user-select: none }` (cf.
    # webview/js/customize.js), ce qui empêche de copier un montant, un libellé
    # d'opération ou un nom de titre — alors que la même page, ouverte dans un
    # navigateur pendant le développement, se sélectionne normalement. C'est la
    # raison pour laquelle le problème ne se voit QUE dans l'app packagée.
    # `js_api` : le sélecteur de fichiers du SYSTÈME, exposé à la page sous
    # `window.pywebview.api` (cf. ApiBureau). Sans lui, l'écran de premier
    # démarrage n'aurait que la saisie du chemin à la main — un navigateur ne
    # donne jamais le chemin complet d'un fichier choisi.
    webview.create_window(
        TITRE,
        url,
        width=1280,
        height=860,
        min_size=(900, 600),
        text_select=True,
        js_api=ApiBureau(),
    )
    webview.start()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        _signaler_erreur("Erreur inattendue au démarrage.\n\n" + traceback.format_exc())
        sys.exit(1)
