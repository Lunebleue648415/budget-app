"""Migration 0034 : visibilité d'une catégorie sur le dashboard.

Ajout purement additif. Ce qui compte : les catégories déjà en base restent
VISIBLES (le dashboard ne doit pas se vider au premier lancement après mise à
jour), et le retour en arrière rend la table à son état d'avant.
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


def _seed_categorie(db_path: Path, nom: str) -> int:
    conn = sqlite3.connect(db_path)
    curseur = conn.execute("INSERT INTO categorie (nom, ordre) VALUES (?, 0)", (nom,))
    categorie_id = curseur.lastrowid
    conn.commit()
    conn.close()
    return categorie_id


def test_0034_les_categories_existantes_restent_visibles(tmp_path):
    db_path = tmp_path / "r0034.db"
    _alembic(db_path, "upgrade", "0033")
    # Un nom qui n'est pas déjà semé par les migrations (categorie.nom est unique).
    categorie_id = _seed_categorie(db_path, "Brocante")

    _alembic(db_path, "upgrade", "0034")

    conn = sqlite3.connect(db_path)
    nom, visible = conn.execute(
        "SELECT nom, visible_dashboard FROM categorie WHERE id = ?", (categorie_id,)
    ).fetchone()
    conn.close()
    assert nom == "Brocante"
    # 1 et non NULL : l'écran doit être identique avant et après la mise à jour.
    assert visible == 1


def test_0034_le_retour_arriere_retire_la_colonne(tmp_path):
    db_path = tmp_path / "r0034_retour.db"
    _alembic(db_path, "upgrade", "0034")
    categorie_id = _seed_categorie(db_path, "Vide-grenier")

    _alembic(db_path, "downgrade", "0033")

    assert "visible_dashboard" not in _colonnes(db_path, "categorie")
    conn = sqlite3.connect(db_path)
    (nom,) = conn.execute("SELECT nom FROM categorie WHERE id = ?", (categorie_id,)).fetchone()
    conn.close()
    assert nom == "Vide-grenier"
