import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from app import database

BACKEND_DIR = Path(__file__).resolve().parents[1]
# `sys.executable` et non `.venv/Scripts/python.exe` : ce dernier suppose un
# venv Windows créé à la main, qui n'existe jamais sur les runners de CI
# (`actions/setup-python` installe directement dans le Python du système,
# quel que soit l'OS) -- l'ancien chemin n'aurait fonctionné nulle part en CI.
# `sys.executable` est l'interpréteur qui exécute déjà pytest, avec les mêmes
# dépendances installées : c'est le seul chemin garanti d'exister, en local
# comme en CI, sur les trois systèmes.
PYTHON = sys.executable


@pytest.fixture()
def restaurer_base_apres_test():
    """L'état de la base courante est un singleton process-wide (cf.
    database._etat) : le restaurer après chaque test évite qu'un test laisse
    l'app pointée ailleurs pour la suite de la session pytest.

    `chemin_avant` PEUT NE PAS ENCORE EXISTER COMME FICHIER : c'est le cas de
    la base de dev par défaut sur un dépôt qu'on vient de cloner, SQLite ne la
    créant qu'à la première connexion réelle (cf. database._appliquer, appelé
    une fois à l'import du module, sans jamais écrire sur le disque). Sans
    cette création, `changer_base` refuserait de restaurer un chemin qu'il ne
    trouve pas -- alors qu'il s'agit précisément du chemin de départ, jamais
    touché par le test lui-même."""
    chemin_avant = database.get_chemin_actuel()
    yield
    if not chemin_avant.is_file():
        chemin_avant.parent.mkdir(parents=True, exist_ok=True)
        chemin_avant.touch()
    database.changer_base(str(chemin_avant))


def _creer_fichier_sqlite_valide(dossier: Path) -> Path:
    chemin = dossier / "autre_base.db"
    conn = sqlite3.connect(chemin)
    conn.execute("CREATE TABLE test (id INTEGER)")
    conn.commit()
    conn.close()
    return chemin


def test_changer_base_bascule_vers_un_fichier_existant(tmp_path, restaurer_base_apres_test):
    chemin = _creer_fichier_sqlite_valide(tmp_path)

    resultat = database.changer_base(str(chemin))

    assert resultat == chemin.resolve()
    assert database.get_chemin_actuel() == chemin.resolve()


def test_changer_base_fichier_introuvable_leve_et_garde_l_etat(tmp_path, restaurer_base_apres_test):
    chemin_avant = database.get_chemin_actuel()
    chemin_absent = tmp_path / "n_existe_pas.db"

    with pytest.raises(FileNotFoundError):
        database.changer_base(str(chemin_absent))

    assert database.get_chemin_actuel() == chemin_avant


def test_changer_base_fichier_invalide_leve_et_garde_l_etat(tmp_path, restaurer_base_apres_test):
    chemin_avant = database.get_chemin_actuel()
    chemin_invalide = tmp_path / "pas_une_base.db"
    chemin_invalide.write_text("ceci n'est pas une base sqlite")

    with pytest.raises(ValueError):
        database.changer_base(str(chemin_invalide))

    assert database.get_chemin_actuel() == chemin_avant


def test_get_db_utilise_la_base_courante_apres_bascule(tmp_path, restaurer_base_apres_test):
    chemin = _creer_fichier_sqlite_valide(tmp_path)
    database.changer_base(str(chemin))

    db = next(database.get_db())
    try:
        lignes = db.execute(text("SELECT name FROM sqlite_master")).all()
    finally:
        db.close()

    assert [row[0] for row in lignes] == ["test"]


def test_dev_db_path_reste_constant_apres_une_bascule(tmp_path, restaurer_base_apres_test):
    chemin_dev_avant = database.DEV_DB_PATH
    chemin = _creer_fichier_sqlite_valide(tmp_path)

    database.changer_base(str(chemin))

    assert database.DEV_DB_PATH == chemin_dev_avant


# ---------- Mise à niveau du schéma à la bascule ----------
#
# L'application de bureau applique les migrations au démarrage, mais sur la
# base résolue à ce moment-là — la base de test, à côté de l'exécutable. La
# base PERSONNELLE ne se rejoint qu'après coup, via le panneau « Base de
# données » : elle n'était donc jamais migrée et restait à l'ancien schéma sous
# une application neuve. Symptôme : 500 « no such column » dès la page
# Opérations, juste après une mise à jour — ce qui ressemble à s'y méprendre à
# une base abîmée par la dernière migration, alors qu'elle n'a jamais été
# migrée.


def _base_app_reelle(dossier: Path, revision: str = "0030") -> Path:
    """Une VRAIE base de l'application arrêtée à une révision antérieure : le
    schéma entier, pas seulement un numéro de version — c'est sur les tables
    réelles que la migration suivante doit pouvoir s'appliquer."""
    chemin = dossier / "perso.db"
    env = {**os.environ, "BUDGET_DB_PATH": str(chemin)}
    resultat = subprocess.run(
        [str(PYTHON), "-m", "alembic", "upgrade", revision],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert resultat.returncode == 0, resultat.stderr
    return chemin


def _base_app_factice(dossier: Path, revision: str) -> Path:
    """Le seul marqueur de version, sans les tables : suffit aux cas qui
    n'exécutent aucune migration."""
    chemin = dossier / "perso.db"
    conn = sqlite3.connect(chemin)
    conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
    conn.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
    conn.commit()
    conn.close()
    return chemin


def test_une_base_personnelle_en_retard_est_migree_a_la_bascule(
    tmp_path, restaurer_base_apres_test
):
    chemin = _base_app_reelle(tmp_path)

    database.changer_base(str(chemin))

    assert database.revision_actuelle(chemin) == database.revision_cible()


def test_la_bascule_copie_la_base_avant_de_la_migrer(tmp_path, restaurer_base_apres_test):
    """La copie est prise AVANT : c'est le seul état auquel on puisse revenir
    si la migration se révèle fautive."""
    chemin = _base_app_reelle(tmp_path)

    database.changer_base(str(chemin))
    sauvegarde, revision_quittee = database.derniere_migration()

    assert revision_quittee == "0030"
    assert sauvegarde is not None and sauvegarde.is_file()
    assert database.revision_actuelle(sauvegarde) == "0030"


def test_une_base_deja_a_jour_nest_ni_copiee_ni_migree(tmp_path, restaurer_base_apres_test):
    chemin = _base_app_factice(tmp_path, revision=database.revision_cible())

    database.changer_base(str(chemin))

    assert database.derniere_migration() == (None, None)
    assert list(tmp_path.glob("perso.avant-*.db")) == []


def test_un_sqlite_etranger_nest_jamais_transforme_en_base_de_lapp(
    tmp_path, restaurer_base_apres_test
):
    """Un fichier sans `alembic_version` n'est pas une base de l'application :
    y déverser tout le schéma serait le pire des services à rendre à quelqu'un
    qui s'est trompé de fichier."""
    chemin = _creer_fichier_sqlite_valide(tmp_path)

    database.changer_base(str(chemin))

    conn = sqlite3.connect(chemin)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    conn.close()
    assert tables == {"test"}


def test_une_migration_impossible_laisse_lapp_sur_la_base_precedente(
    tmp_path, restaurer_base_apres_test
):
    """Une base à moitié migrée est pire qu'une bascule refusée."""
    chemin_avant = database.get_chemin_actuel()
    chemin = _base_app_factice(tmp_path, revision="revision-qui-nexiste-pas")

    with pytest.raises(ValueError):
        database.changer_base(str(chemin))

    assert database.get_chemin_actuel() == chemin_avant
