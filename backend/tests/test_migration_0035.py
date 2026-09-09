"""Migration 0035 : couleur figée d'une catégorie.

Ce qui compte : les catégories déjà en base gardent EXACTEMENT la couleur
qu'elles avaient à l'écran (celle de leur position), sans quoi l'histogramme
changerait de couleurs au premier lancement après mise à jour — le défaut même
que cette colonne vient supprimer.
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


def test_0035_la_couleur_reprend_lordre_daffichage(tmp_path):
    db_path = tmp_path / "r0035.db"
    _alembic(db_path, "upgrade", "0034")

    conn = sqlite3.connect(db_path)
    # Un ordre volontairement décousu : c'est LUI qui doit être repris, pas l'id.
    ids = [r[0] for r in conn.execute("SELECT id FROM categorie ORDER BY id")]
    for position, categorie_id in enumerate(reversed(ids)):
        conn.execute(
            "UPDATE categorie SET ordre = ? WHERE id = ?", (position, categorie_id)
        )
    conn.commit()
    conn.close()

    _alembic(db_path, "upgrade", "0035")

    conn = sqlite3.connect(db_path)
    lignes = conn.execute(
        "SELECT couleur_index FROM categorie ORDER BY ordre, id"
    ).fetchall()
    conn.close()
    # 0, 1, 2… dans l'ordre d'affichage : exactement ce que faisait le calcul
    # par position qu'on remplace.
    assert [c for (c,) in lignes] == list(range(len(ids)))


def test_0035_le_retour_arriere_retire_la_colonne(tmp_path):
    db_path = tmp_path / "r0035_retour.db"
    _alembic(db_path, "upgrade", "0035")

    _alembic(db_path, "downgrade", "0034")

    assert "couleur_index" not in _colonnes(db_path, "categorie")
    # visible_dashboard (0034) est toujours là : on n'est pas descendu plus bas.
    assert "visible_dashboard" in _colonnes(db_path, "categorie")
