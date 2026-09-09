"""Migration 0040 : un titre peut être archivé.

Ce qui compte : un titre déjà en base reste EN SERVICE. Une migration ne change
pas ce que fait la base, seulement ce qu'elle permet — et voir sa liste de
titres se vider après une mise à jour serait exactement le contraire. Et le
retour arrière laisse la table telle qu'avant, cours et lien compris.
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


def _colonnes(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    colonnes = {ligne[1] for ligne in conn.execute(f"PRAGMA table_info({table})")}
    conn.close()
    return colonnes


def _creer_action(conn, nom: str, valeur: float) -> None:
    monnaie_id = conn.execute("SELECT id FROM monnaie LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO action (nom, valeur, monnaie_id) VALUES (?, ?, ?)",
        (nom, valeur, monnaie_id),
    )
    conn.commit()


def test_0040_un_titre_existant_reste_en_service(tmp_path):
    db_path = tmp_path / "r0040.db"
    _alembic(db_path, "upgrade", "0039")

    conn = sqlite3.connect(db_path)
    _creer_action(conn, "Air Liquide", 167.12)
    conn.close()

    _alembic(db_path, "upgrade", "0040")

    conn = sqlite3.connect(db_path)
    ligne = conn.execute("SELECT nom, valeur, archivee FROM action").fetchone()
    conn.close()
    # `archivee` à 0 : rien n'a été rangé dans le dos de l'utilisateur.
    assert ligne == ("Air Liquide", 167.12, 0)


def test_0040_le_retour_arriere_retire_la_colonne_sans_perdre_le_titre(tmp_path):
    db_path = tmp_path / "r0040_retour.db"
    _alembic(db_path, "upgrade", "0040")

    conn = sqlite3.connect(db_path)
    _creer_action(conn, "Air Liquide", 167.12)
    conn.execute("UPDATE action SET archivee = 1")
    conn.commit()
    conn.close()

    _alembic(db_path, "downgrade", "0039")

    assert "archivee" not in _colonnes(db_path, "action")
    conn = sqlite3.connect(db_path)
    # Le titre revient simplement dans les listes : on n'a retiré qu'un
    # classement, pas une donnée du budget.
    assert conn.execute("SELECT nom, valeur FROM action").fetchone() == (
        "Air Liquide",
        167.12,
    )
    conn.close()
