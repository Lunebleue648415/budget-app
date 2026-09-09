"""La migration 0020 s'applique sur une base 0019 déjà peuplée.

Comme test_migration_0019, ces tests appellent alembic en sous-processus : les
autres tests construisent le schéma via `Base.metadata.create_all` et ne
passeraient donc jamais par le script de migration lui-même — précisément là où
se cachent les erreurs qui ne se voient que sur une vraie base existante.
"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
# `sys.executable` et non `.venv/Scripts/python.exe` : ce dernier suppose un
# venv Windows créé à la main, qui n'existe jamais sur les runners de CI
# (`actions/setup-python` installe directement dans le Python du système,
# quel que soit l'OS) -- l'ancien chemin n'aurait fonctionné nulle part en CI.
# `sys.executable` est l'interpréteur qui exécute déjà pytest, avec les mêmes
# dépendances installées : c'est le seul chemin garanti d'exister, en local
# comme en CI, sur les trois systèmes.
PYTHON = sys.executable


def _alembic(db_path: Path, revision: str):
    env = {**os.environ, "BUDGET_DB_PATH": str(db_path)}
    resultat = subprocess.run(
        [str(PYTHON), "-m", "alembic", "upgrade", revision],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert resultat.returncode == 0, resultat.stderr
    return resultat


def _seed_base_0019(db_path: Path):
    """Une base ordinaire : un compte courant et une opération classique. Ce que
    0020 ajoute ne doit toucher ni l'un ni l'autre."""
    conn = sqlite3.connect(db_path)
    type_courant = conn.execute("select id from type_compte where nom='courant'").fetchone()[0]
    conn.execute(
        "INSERT INTO compte (nom, type_id, solde_initial) VALUES ('Courant', ?, 100)",
        (type_courant,),
    )
    categorie = conn.execute("select id from categorie where nom='Autres'").fetchone()[0]
    type_classique = conn.execute(
        "select id from type_operation where code='classique'"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO operation (date,compte_id,type_id,categorie_id,nature,montant,sens,statut,"
        "montant_du,montant_a_rembourser,recurrente) "
        "VALUES ('2026-01-01',1,?,?,'Loyer',500,'dépense','réel',0,0,0)",
        (type_classique, categorie),
    )
    conn.commit()
    conn.close()


def test_migration_0020_ajoute_les_placements_sans_toucher_a_lexistant(tmp_path):
    db_path = tmp_path / "repro_0020.db"
    _alembic(db_path, "0019")
    _seed_base_0019(db_path)

    _alembic(db_path, "0020")

    conn = sqlite3.connect(db_path)
    # Le troisième type de compte protégé.
    assert conn.execute(
        "select systeme from type_compte where nom='placements financiers'"
    ).fetchone() == (1,)
    # Le type d'opération des titres, marqué interne ; les six autres non.
    types = dict(conn.execute("select code, interne from type_operation").fetchall())
    assert types["action"] == 1
    assert {code for code, interne in types.items() if interne} == {"action"}
    # Les tables de titres existent et sont vides.
    assert conn.execute("select count(*) from action").fetchone() == (0,)
    assert conn.execute("select count(*) from operation_action").fetchone() == (0,)
    # L'opération existante est intacte.
    assert conn.execute("select nature, montant from operation").fetchall() == [("Loyer", 500.0)]
    conn.close()


def test_downgrade_0020_retire_titres_et_type_de_compte(tmp_path):
    db_path = tmp_path / "downgrade_0020.db"
    _alembic(db_path, "0020")

    env = {**os.environ, "BUDGET_DB_PATH": str(db_path)}
    resultat = subprocess.run(
        [str(PYTHON), "-m", "alembic", "downgrade", "0019"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert resultat.returncode == 0, resultat.stderr

    conn = sqlite3.connect(db_path)
    tables = {row[0] for row in conn.execute("select name from sqlite_master where type='table'")}
    assert "action" not in tables and "operation_action" not in tables
    assert conn.execute("select count(*) from type_operation where code='action'").fetchone() == (0,)
    assert conn.execute(
        "select count(*) from type_compte where nom='placements financiers'"
    ).fetchone() == (0,)
    conn.close()
