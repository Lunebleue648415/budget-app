"""Migration 0036 : amortissement d'une opération sur plusieurs mois.

Ce qui compte : les opérations déjà en base ne deviennent amorties par accident
(elles pèseraient alors sur des mois que personne n'a choisis), et le retour
arrière laisse la table telle qu'avant.
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


def _creer_operation(conn, nature: str) -> None:
    """Une opération minimale, avec le compte et le type que la base migrée
    fournit déjà."""
    compte_id = conn.execute("SELECT id FROM compte LIMIT 1").fetchone()
    if compte_id is None:
        type_compte_id = conn.execute("SELECT id FROM type_compte LIMIT 1").fetchone()[0]
        conn.execute(
            "INSERT INTO compte (nom, type_id, ordre) VALUES (?, ?, 0)",
            ("Courant", type_compte_id),
        )
        compte_id = conn.execute("SELECT id FROM compte LIMIT 1").fetchone()
    monnaie_id = conn.execute("SELECT id FROM monnaie LIMIT 1").fetchone()[0]
    type_id = conn.execute(
        "SELECT id FROM type_operation WHERE code = 'classique'"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO operation (date, compte_id, type_id, nature, montant, monnaie_id,"
        " sens, statut, montant_du, montant_a_rembourser, recurrente)"
        " VALUES ('2026-07-15', ?, ?, ?, 100.0, ?, 'dépense', 'réel', 0, 0, 0)",
        (compte_id[0], type_id, nature, monnaie_id),
    )
    conn.commit()


def test_0036_les_operations_existantes_ne_sont_pas_amorties(tmp_path):
    db_path = tmp_path / "r0036.db"
    _alembic(db_path, "upgrade", "0035")

    conn = sqlite3.connect(db_path)
    _creer_operation(conn, "Courses")
    conn.close()

    _alembic(db_path, "upgrade", "0036")

    conn = sqlite3.connect(db_path)
    ligne = conn.execute(
        "SELECT amorti, amortissement_debut, amortissement_fin FROM operation"
    ).fetchone()
    conn.close()
    # Faux, et sans bornes : exactement ce que dit « cette dépense pèse sur son
    # propre mois », le comportement d'avant la migration.
    assert ligne == (0, None, None)


def test_0036_le_retour_arriere_retire_les_trois_colonnes(tmp_path):
    db_path = tmp_path / "r0036_retour.db"
    _alembic(db_path, "upgrade", "0036")

    _alembic(db_path, "downgrade", "0035")

    colonnes = _colonnes(db_path, "operation")
    assert "amorti" not in colonnes
    assert "amortissement_debut" not in colonnes
    assert "amortissement_fin" not in colonnes
    # Les notes (0031) sont toujours là : on n'est pas descendu plus bas.
    assert "notes" in colonnes
