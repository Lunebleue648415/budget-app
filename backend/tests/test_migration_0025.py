"""La migration 0025 donne un ordre d'affichage aux comptes.

Le point à vérifier est que l'ordre initial REPRODUIT l'affichage d'avant :
l'ordre alphabétique, type par type. Une migration qui laisserait tout le monde
à 0 ferait basculer les cartes du dashboard dans l'ordre des id — un
réarrangement gratuit, jamais demandé, le jour de la mise à jour.
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


def _alembic(db_path: Path, commande: str, revision: str):
    env = {**os.environ, "BUDGET_DB_PATH": str(db_path)}
    resultat = subprocess.run(
        [str(PYTHON), "-m", "alembic", commande, revision],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert resultat.returncode == 0, resultat.stderr
    return resultat


def _seed_comptes(db_path: Path):
    """Deux types, des comptes insérés dans le désordre alphabétique : c'est
    seulement ainsi que l'ordre initial se distingue de l'ordre des id."""
    conn = sqlite3.connect(db_path)
    types = {
        nom: id_
        for id_, nom in conn.execute("select id, nom from type_compte").fetchall()
    }
    for nom, type_nom in (
        ("Zébu", "courant"),
        ("Abeille", "courant"),
        ("Muguet", "courant"),
        ("Zinnia", "épargne"),
        ("Aster", "épargne"),
    ):
        conn.execute(
            "INSERT INTO compte (nom, type_id) VALUES (?, ?)", (nom, types[type_nom])
        )
    conn.commit()
    conn.close()
    return types


def test_l_ordre_initial_est_l_ordre_alphabetique_de_chaque_type(tmp_path):
    db_path = tmp_path / "ordre_0025.db"
    _alembic(db_path, "upgrade", "0024")
    types = _seed_comptes(db_path)

    _alembic(db_path, "upgrade", "0025")

    conn = sqlite3.connect(db_path)
    for type_nom in ("courant", "épargne"):
        noms = [
            row[0]
            for row in conn.execute(
                "select nom from compte where type_id = ? order by ordre",
                (types[type_nom],),
            )
        ]
        assert noms == sorted(noms), f"type {type_nom} : {noms}"
    # Chaque type est numéroté à partir de 0, indépendamment des autres :
    # l'ordre ne se lit qu'au sein d'un type.
    for type_nom in ("courant", "épargne"):
        ordres = [
            row[0]
            for row in conn.execute(
                "select ordre from compte where type_id = ? order by ordre",
                (types[type_nom],),
            )
        ]
        assert ordres == list(range(len(ordres)))
    conn.close()


def test_downgrade_0025_retire_l_ordre_sans_toucher_aux_comptes(tmp_path):
    db_path = tmp_path / "downgrade_0025.db"
    _alembic(db_path, "upgrade", "0024")
    _seed_comptes(db_path)
    _alembic(db_path, "upgrade", "0025")

    _alembic(db_path, "downgrade", "0024")

    conn = sqlite3.connect(db_path)
    colonnes = {row[1] for row in conn.execute("PRAGMA table_info(compte)")}
    assert "ordre" not in colonnes
    assert conn.execute("select count(*) from compte").fetchone()[0] == 5
    conn.close()
