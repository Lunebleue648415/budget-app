"""La migration 0031 ajoute la colonne `notes` aux opérations.

Un champ purement additif : ce qu'on vérifie ici, c'est qu'il n'écrase rien et
qu'il vaut NULL pour tout ce qui existait avant — une opération jamais annotée
ne doit pas se retrouver avec une chaîne vide qui ferait croire à une note.
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


def _seed_operation(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    type_id = conn.execute(
        "SELECT id FROM type_operation WHERE code = 'classique'"
    ).fetchone()[0]
    monnaie_id = conn.execute("SELECT id FROM monnaie LIMIT 1").fetchone()[0]
    compte_type_id = conn.execute(
        "SELECT id FROM type_compte WHERE nom = 'courant'"
    ).fetchone()[0]
    curseur = conn.execute(
        "INSERT INTO compte (nom, type_id, ordre) VALUES ('Courant', ?, 0)",
        (compte_type_id,),
    )
    compte_id = curseur.lastrowid
    conn.execute(
        "INSERT INTO compte_monnaie (compte_id, monnaie_id, solde_initial, ordre) "
        "VALUES (?, ?, 0, 0)",
        (compte_id, monnaie_id),
    )
    curseur = conn.execute(
        "INSERT INTO operation (date, compte_id, type_id, nature, montant, monnaie_id, "
        "sens, statut, montant_du, montant_a_rembourser, recurrente) "
        "VALUES ('2026-01-05', ?, ?, 'Courses', 20.0, ?, 'dépense', 'réel', 0, 0, 0)",
        (compte_id, type_id, monnaie_id),
    )
    operation_id = curseur.lastrowid
    conn.commit()
    conn.close()
    return operation_id


def test_les_operations_existantes_survivent_sans_note(tmp_path):
    db_path = tmp_path / "initial_0031.db"
    _alembic(db_path, "upgrade", "0030")
    operation_id = _seed_operation(db_path)

    _alembic(db_path, "upgrade", "0031")

    conn = sqlite3.connect(db_path)
    nature, montant, notes = conn.execute(
        "SELECT nature, montant, notes FROM operation WHERE id = ?", (operation_id,)
    ).fetchone()
    conn.close()
    assert (nature, montant) == ("Courses", 20.0)
    # NULL, et pas "" : rien n'a été écrit, et l'app doit pouvoir le dire.
    assert notes is None


def test_le_retour_arriere_retire_la_colonne(tmp_path):
    db_path = tmp_path / "retour_0031.db"
    _alembic(db_path, "upgrade", "0031")
    operation_id = _seed_operation(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE operation SET notes = 'à revoir' WHERE id = ?", (operation_id,))
    conn.commit()
    conn.close()

    _alembic(db_path, "downgrade", "0030")

    conn = sqlite3.connect(db_path)
    colonnes = {ligne[1] for ligne in conn.execute("PRAGMA table_info(operation)")}
    # L'opération elle-même reste, seule la note disparaît.
    (nature,) = conn.execute(
        "SELECT nature FROM operation WHERE id = ?", (operation_id,)
    ).fetchone()
    conn.close()
    assert "notes" not in colonnes
    assert nature == "Courses"
