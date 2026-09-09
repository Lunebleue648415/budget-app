import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, declarative_base

# Sépare l'environnement de développement (données factices, dans le repo) de
# la production (données réelles, hors du repo). BUDGET_DB_PATH pointe
# explicitement vers un fichier .db ; sans cette variable, on utilise toujours
# la base de dev locale — jamais de bascule implicite vers un chemin de prod.
_BACKEND_DIR = Path(__file__).resolve().parent.parent


def _dossier_donnees_par_defaut() -> Path:
    """Emplacement de la base de test/dev.

    En application packagée (PyInstaller), le code tourne depuis le bundle,
    qui est remplacé à chaque reconstruction : la base doit donc vivre À CÔTÉ
    de l'exécutable, pas dedans, pour survivre à une mise à jour de l'app.
    En développement, l'emplacement historique dans le repo est conservé.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "data"
    return _BACKEND_DIR / "data" / "dev"


_DEFAULT_DEV_DIR = _dossier_donnees_par_defaut()
# `exist_ok` NE SUFFIT PAS : l'emplacement peut être en lecture seule (bundle
# macOS lancé depuis la quarantaine, donc « translocated » sur un montage en
# lecture seule ; application posée dans /Applications ou Program Files). Sans
# cette garde, l'import du module échoue et l'application meurt avant d'ouvrir
# sa fenêtre — alors qu'elle a désormais tout ce qu'il faut pour demander à
# l'utilisateur où ranger sa base (cf. configuration_requise). Même
# raisonnement que extensions.preparer_dossiers.
try:
    _DEFAULT_DEV_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass
_DEFAULT_DEV_DB_PATH = _DEFAULT_DEV_DIR / "budget_dev.db"

# Chemin de la base de test/dev, exposé pour que l'app puisse toujours y
# revenir facilement (bouton "Revenir à la base de test").
#
# C'est aussi l'ANCRE DE TOUT CE QUI N'EST PAS DES DONNÉES et vit à côté de
# l'exécutable : `extensions.json` (état des extensions) et `erreur.log`. Ces
# deux-là ne suivent PAS la base quand elle déménage — ils décrivent
# l'installation, pas les finances.
DEV_DB_PATH = _DEFAULT_DEV_DB_PATH.resolve()


def _chemin_impose_par_environnement() -> Path | None:
    """BUDGET_DB_PATH, quand elle est posée. Elle PRIME SUR TOUT — sur le choix
    mémorisé comme sur le défaut — et désactive au passage la configuration
    forcée : c'est par elle que passent les tests et les bacs à sable, qui
    n'ont rien à demander à personne."""
    valeur = os.environ.get("BUDGET_DB_PATH")
    return Path(valeur).expanduser() if valeur else None


# Renseigné quand un chemin ÉTAIT mémorisé mais que le fichier a disparu :
# disque externe débranché, dossier renommé, fichier supprimé. L'application
# repart alors sur son emplacement par défaut, mais le panneau « Base de
# données » le dit en toutes lettres — c'est la seule chose qui distingue
# « ta base n'est pas là où tu l'avais mise » de « tu n'as jamais rien saisi ».
BASE_MEMORISEE_INTROUVABLE: Path | None = None


def _resoudre_chemin_demarrage() -> Path:
    """La base sur laquelle l'application s'ouvre, dans l'ordre de priorité :
    la variable d'environnement, puis le choix mémorisé au dernier passage par
    le panneau « Base de données », puis l'emplacement par défaut.

    LE DÉFAUT EST À RISQUE et c'est assumé : il vit dans le dossier de
    l'application, qu'une mise à jour remplace (cf. chemin_a_risque). Y
    retomber n'est pas un accident silencieux — c'est exactement la condition
    qui déclenche la demande de configuration au démarrage.

    UN CHEMIN MÉMORISÉ DONT LE FICHIER A DISPARU NE SERT PAS DE CIBLE. SQLite
    crée le fichier qu'on lui désigne, et les migrations le rempliraient d'un
    schéma vierge : l'utilisateur retrouverait une application parfaitement
    fonctionnelle et parfaitement vide, à l'endroit exact où il croyait avoir
    ses données — et le vrai fichier, sur le disque débranché, n'aurait plus
    rien pour le rattacher à l'application. On repart donc du défaut, en
    laissant une trace de ce qu'on cherchait."""
    global BASE_MEMORISEE_INTROUVABLE

    impose = _chemin_impose_par_environnement()
    if impose is not None:
        return impose
    # LE CHOIX MÉMORISÉ NE VAUT QUE POUR L'APPLICATION PACKAGÉE. En
    # développement, la base est celle du dépôt, et `alembic upgrade` lancé à la
    # main depuis `backend/` doit continuer de la viser — sinon il migrerait la
    # base PERSONNELLE de la machine de développement, sans le dire et sans
    # qu'on l'ait demandé, du seul fait qu'un fichier de configuration traîne
    # dans le profil. C'est exactement le genre de bascule implicite que le
    # module refuse depuis toujours.
    if not getattr(sys, "frozen", False) and os.environ.get("BUDGET_FORCER_CHOIX_BASE") != "1":
        return _DEFAULT_DEV_DB_PATH
    from . import config_utilisateur

    memorise = config_utilisateur.chemin_base_memorise()
    if memorise is None:
        return _DEFAULT_DEV_DB_PATH
    if memorise.is_file():
        return memorise
    BASE_MEMORISEE_INTROUVABLE = memorise
    return _DEFAULT_DEV_DB_PATH


# Utilisés par alembic (migrations, cf. alembic/env.py) : résolution statique à
# l'import, indépendante de la bascule de base à chaud ci-dessous. Elle suit
# désormais le choix mémorisé, sans quoi l'application de bureau migrerait au
# démarrage une base par défaut que plus personne n'ouvre, en laissant la vraie
# à son ancien schéma (cf. desktop/app_desktop.py::_appliquer_migrations).
DATABASE_PATH = _resoudre_chemin_demarrage()
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"

Base = declarative_base()


class _EtatBase:
    """Le moteur/la session courants ne sont jamais fixes : toutes les
    opérations CRUD passent par get_db(), qui lit toujours cet état — changer_base()
    peut donc rediriger l'app entière vers un autre fichier .db à chaud, sans
    redémarrage ni changement dans les routeurs."""

    def __init__(self):
        self.engine = None
        self.SessionLocal = None
        self.chemin: Path = None
        # Trace de la dernière bascule ayant migré la base : le panneau « Base
        # de données » les affiche, pour que la copie de sécurité soit connue
        # de l'utilisateur AU MOMENT où le schéma change, et pas seulement
        # quand il la cherche.
        self.derniere_sauvegarde: Path = None
        self.revision_quittee: str = None


_etat = _EtatBase()


def _construire(chemin: Path):
    url = f"sqlite:///{chemin.as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, SessionLocal


def _appliquer(chemin: Path):
    engine, SessionLocal = _construire(chemin)
    ancien_engine = _etat.engine
    _etat.engine, _etat.SessionLocal, _etat.chemin = engine, SessionLocal, chemin
    if ancien_engine is not None:
        ancien_engine.dispose()


def get_chemin_actuel() -> Path:
    return _etat.chemin


def _dossier_alembic() -> Path:
    """Où vivent env.py et versions/*.py : dans le bundle extrait en mode
    packagé, dans le repo sinon (même résolution que desktop/app_desktop.py)."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "alembic"
    return _BACKEND_DIR / "alembic"


def revision_actuelle(chemin: Path) -> str | None:
    """La révision inscrite dans le fichier, ou None s'il n'en porte aucune
    (base vierge, ou fichier qui n'est pas une base de l'app)."""
    moteur = create_engine(f"sqlite:///{chemin.as_posix()}")
    try:
        with moteur.connect() as connexion:
            ligne = connexion.execute(text("SELECT version_num FROM alembic_version")).first()
            return ligne[0] if ligne else None
    except Exception:
        return None
    finally:
        moteur.dispose()


def revision_cible() -> str | None:
    """La révision qu'attend CETTE version de l'application."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config()
    config.set_main_option("script_location", str(_dossier_alembic()))
    return ScriptDirectory.from_config(config).get_current_head()


def derniere_migration() -> tuple[Path | None, str | None]:
    """(copie de sécurité, révision quittée) de la dernière bascule ayant migré
    la base — (None, None) si la dernière n'a rien eu à faire."""
    return _etat.derniere_sauvegarde, _etat.revision_quittee


def sauvegarder_avant_migration(chemin: Path, revision: str | None) -> Path:
    """Copie horodatée à côté du fichier, prise AVANT toute migration.

    Une migration réussie ne perd rien, mais c'est précisément le moment où
    l'on regrette de ne pas avoir de copie : le schéma change sous des données
    qu'on ne peut pas reconstituer. Nommée d'après la révision quittée, pour
    savoir d'un coup d'œil à quel état on reviendrait."""
    horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
    cible = chemin.with_name(f"{chemin.stem}.avant-{revision or 'vierge'}_{horodatage}{chemin.suffix}")
    shutil.copy2(chemin, cible)
    return cible


def migrer_si_necessaire(chemin: Path) -> tuple[Path | None, str | None]:
    """Amène `chemin` au schéma de l'application. Renvoie (sauvegarde, révision
    quittée), les deux None si la base était déjà à jour.

    POURQUOI ICI. L'application de bureau applique les migrations au démarrage
    (cf. desktop/app_desktop.py), mais sur la base résolue à ce moment-là — la
    base de test, à côté de l'exécutable. La base PERSONNELLE, elle, ne se
    rejoint qu'après coup, en saisissant son chemin dans le panneau « Base de
    données » : elle n'était donc jamais migrée, et restait à l'ancien schéma
    sous une application neuve. Le symptôme n'a rien d'explicite — un 500 sur
    « no such column: operation.notes » dès la page Opérations, juste après une
    mise à jour, ce qui ressemble à une base abîmée par la migration alors
    qu'elle n'a simplement jamais été migrée."""
    revision = revision_actuelle(chemin)
    # Sans `alembic_version`, le fichier n'est pas une base de l'application :
    # ce peut être n'importe quel SQLite que l'utilisateur a désigné par erreur,
    # et y déverser tout le schéma serait le pire des services à lui rendre.
    # `changer_base` ne crée jamais rien implicitement — migrer ici non plus.
    if revision is None or revision == revision_cible():
        return None, None

    from alembic import command
    from alembic.config import Config

    sauvegarde = sauvegarder_avant_migration(chemin, revision)
    config = Config()
    config.set_main_option("script_location", str(_dossier_alembic()))
    # La cible est passée par `attributes` : env.py la préfère à l'URL figée à
    # l'import du processus, qui désigne la base de DÉPART.
    config.attributes["sqlalchemy_url"] = f"sqlite:///{chemin.as_posix()}"
    command.upgrade(config, "head")
    return sauvegarde, revision


def dossier_application() -> Path:
    """Le dossier qu'une mise à jour REMPLACE : celui de l'exécutable en
    application packagée, la racine du dépôt en développement."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _BACKEND_DIR.parent


def chemin_a_risque(chemin: Path) -> bool:
    """Vrai quand la base vit DANS le dossier de l'application.

    C'est le seul emplacement dangereux, et il l'est de deux façons selon le
    système. Sur Windows et Linux, l'archive se décompresse par-dessus
    l'ancienne : `data/` survit si l'utilisateur fusionne, disparaît s'il
    supprime d'abord l'ancien dossier — un coup de pile ou face à chaque mise
    à jour. Sur macOS c'est pire et c'est systématique : la base est dans
    `Budget App.app/Contents/MacOS/data/`, donc DANS le bundle, et le Finder
    remplace un `.app` en entier sans jamais proposer de fusionner.

    Le dossier des extensions court le même risque, mais une extension se
    retélécharge ; une base de comptes, non."""
    try:
        chemin.resolve().relative_to(dossier_application())
        return True
    except (ValueError, OSError):
        return False


def emplacement_propose() -> Path:
    """L'emplacement proposé par défaut au premier démarrage.

    LE DOSSIER « DOCUMENTS » PLUTÔT QU'UN DOSSIER DE CONFIGURATION SYSTÈME :
    c'est un fichier que l'utilisateur a de bonnes raisons de vouloir
    retrouver, copier sur une clé, mettre dans sa sauvegarde. Rangé dans
    AppData ou Application Support, il serait à l'abri des mises à jour mais
    introuvable pour qui le cherche — et une base qu'on ne sait pas sauvegarder
    n'est protégée qu'à moitié."""
    documents = Path.home() / "Documents"
    racine = documents if documents.is_dir() else Path.home()
    return racine / "Budget App" / "budget.db"


def configuration_requise() -> bool:
    """Faut-il exiger de l'utilisateur qu'il choisisse un emplacement AVANT de
    le laisser entrer dans l'application ?

    Oui dès que la base ouverte est dans le dossier de l'application : c'est le
    cas au tout premier démarrage (aucun choix mémorisé, on est sur le défaut)
    comme après une mise à jour qui aurait effacé la configuration. Les deux
    situations appellent le même geste, il n'y a donc qu'une condition.

    DEUX ÉCHAPPATOIRES, et elles se justifient l'une et l'autre :
    BUDGET_DB_PATH, par où passent les tests et les bacs à sable, qui désigne
    déjà explicitement une cible ; et le mode DÉVELOPPEMENT, où la base vit
    dans le dépôt par construction et n'est jamais remplacée par une archive —
    y forcer un choix ne protégerait de rien et casserait le lancement du
    serveur de dev.

    `BUDGET_FORCER_CHOIX_BASE=1` LÈVE LES DEUX, et sert exclusivement à
    regarder cet écran sans reconstruire le bundle. Il lève aussi celle de
    BUDGET_DB_PATH parce que c'est la seule façon de l'essayer SANS RISQUE :
    sans elle, la seule base « à risque » disponible en développement serait
    celle du dépôt — de vraies données, qu'un écran de mise au point n'a rien
    à proposer de déplacer."""
    force = os.environ.get("BUDGET_FORCER_CHOIX_BASE") == "1"
    if not force:
        if _chemin_impose_par_environnement() is not None:
            return False
        if not getattr(sys, "frozen", False):
            return False
    return chemin_a_risque(get_chemin_actuel())


def installer_base(destination: str, deplacer_depuis: str | None = None) -> tuple[Path, str]:
    """Met en place la base à l'emplacement choisi, puis y bascule l'app.

    Rend (chemin, action) où `action` dit ce qui s'est passé — « ouverte »,
    « déplacée », « créée » — parce que ces trois cas n'appellent pas le même
    message à l'écran, et que le frontend ne peut pas le deviner : il ne sait
    pas si le fichier existait avant sa requête.

    C'EST LA SEULE FONCTION QUI CRÉE OU DÉPLACE UN FICHIER DE BASE.
    `changer_base` s'y refuse par principe (un chemin fautif doit échouer, pas
    fabriquer une base vide) — mais le premier démarrage a précisément besoin
    de fabriquer quelque chose, et forcer l'utilisateur à créer un fichier
    SQLite à la main avant de pouvoir ouvrir son budget n'aurait aucun sens."""
    cible = Path(destination).expanduser()
    if cible.is_dir():
        raise ValueError(f"{cible} est un dossier : donne le chemin d'un fichier .db")

    # Le fichier est déjà là : rien à fabriquer, c'est une bascule ordinaire
    # (qui migrera le schéma au besoin). Le cas de qui retrouve sa base après
    # une mise à jour, ou la désigne sur un disque externe.
    if cible.is_file():
        return changer_base(str(cible)), "ouverte"

    try:
        cible.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"Impossible de créer le dossier {cible.parent} : {exc}") from exc

    source = Path(deplacer_depuis).expanduser() if deplacer_depuis else None
    if source is not None and source.is_file():
        # DÉPLACEMENT et non copie : deux fichiers identiques dont un seul est
        # lu sont une invitation à travailler des semaines dans le mauvais, et
        # celui qu'on laisserait derrière est justement dans le dossier que la
        # prochaine mise à jour efface. Les fichiers annexes de SQLite suivent
        # — un `-wal` abandonné à côté de l'ancien emplacement emporterait les
        # dernières transactions avec lui.
        _fermer_base_courante()
        shutil.move(str(source), str(cible))
        for suffixe in ("-wal", "-shm", "-journal"):
            annexe = source.with_name(source.name + suffixe)
            if annexe.is_file():
                shutil.move(str(annexe), str(cible.with_name(cible.name + suffixe)))
        return changer_base(str(cible)), "déplacée"

    # Ni fichier à l'arrivée, ni base à déplacer : on en fabrique une neuve.
    # `upgrade head` sur un chemin inexistant crée le fichier, y pose tout le
    # schéma et son contenu initial (catégories, monnaie par défaut) — c'est
    # exactement ce qui se passe aujourd'hui au premier lancement, simplement
    # ailleurs.
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(_dossier_alembic()))
    config.attributes["sqlalchemy_url"] = f"sqlite:///{cible.as_posix()}"
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        raise ValueError(f"Impossible de créer la base {cible} : {exc}") from exc
    return changer_base(str(cible)), "créée"


def _fermer_base_courante() -> None:
    """Libère le fichier avant de le déplacer. Sous Windows, un fichier encore
    ouvert par le moteur ne se renomme pas — le déplacement échouerait avec un
    « accès refusé » que rien à l'écran ne saurait expliquer."""
    if _etat.engine is not None:
        _etat.engine.dispose()


def changer_base(chemin: str) -> Path:
    """Bascule toutes les opérations CRUD vers un autre fichier SQLite déjà
    existant — jamais de création implicite (un chemin fautif doit échouer
    clairement, pas créer silencieusement une base vide). Si le fichier n'est
    pas une base SQLite exploitable, l'app reste sur la base précédente."""
    nouveau_chemin = Path(chemin).expanduser()
    if not nouveau_chemin.is_file():
        raise FileNotFoundError(f"Fichier introuvable : {nouveau_chemin}")
    nouveau_chemin = nouveau_chemin.resolve()

    engine, SessionLocal = _construire(nouveau_chemin)
    try:
        with SessionLocal() as session:
            # Force réellement la lecture du fichier (contrairement à un
            # "SELECT 1" littéral, jamais évalué contre le disque) : un
            # fichier qui n'est pas une base SQLite valide échoue ici.
            session.execute(text("SELECT * FROM sqlite_master LIMIT 1"))
    except Exception as exc:
        engine.dispose()
        raise ValueError(f"Fichier illisible en tant que base SQLite : {nouveau_chemin}") from exc

    # Le schéma AVANT de basculer : brancher l'app sur une base restée à une
    # version antérieure ne donne pas une app dégradée, mais une app qui répond
    # 500 sur ses pages principales. La migration se fait donc ici, sur une
    # copie de sécurité prise juste avant — et si elle échoue, on ne bascule
    # pas du tout : mieux vaut rester sur la base précédente que se retrouver
    # sur une base à moitié migrée.
    engine.dispose()
    try:
        derniere_sauvegarde, revision_quittee = migrer_si_necessaire(nouveau_chemin)
    except Exception as exc:
        raise ValueError(
            f"Impossible de mettre à jour le schéma de {nouveau_chemin} : {exc}"
        ) from exc
    _etat.derniere_sauvegarde = derniere_sauvegarde
    _etat.revision_quittee = revision_quittee
    engine, SessionLocal = _construire(nouveau_chemin)

    ancien_engine = _etat.engine
    _etat.engine, _etat.SessionLocal, _etat.chemin = engine, SessionLocal, nouveau_chemin
    if ancien_engine is not None:
        ancien_engine.dispose()
    return nouveau_chemin


def get_db():
    db = _etat.SessionLocal()
    try:
        yield db
    finally:
        db.close()


_appliquer(DATABASE_PATH.resolve())

# Session indépendante de la bascule à chaud ci-dessus, résolue une seule fois
# via BUDGET_DB_PATH : réservée aux scripts autonomes (seed_dev.py), qui
# tournent dans un processus séparé et doivent toujours cibler la même base
# que la variable d'environnement, jamais celle sélectionnée dans une
# app en cours d'exécution.
_moteur_scripts = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})


@event.listens_for(_moteur_scripts, "connect")
def _enable_sqlite_foreign_keys_scripts(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_moteur_scripts)
