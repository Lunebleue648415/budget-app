"""La migration 0027 rend le vocabulaire de la colonne « Sens » propre au preset.

Le point à vérifier est qu'elle n'active rien : un preset existant repart avec
deux listes VIDES, ce qui veut dire « le vocabulaire français du code », donc
exactement le comportement d'avant. Des listes préremplies au moment de la
migration figeraient au contraire une copie qui ne suivrait plus les évolutions
de constants.LIBELLES_SENS_*.
"""
import json
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


def _seed_preset(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    curseur = conn.execute(
        "INSERT INTO import_preset (nom, colonnes, colonnes_exclues_comparaison, "
        "ignorer_premiere_ligne) VALUES (?, ?, ?, 0)",
        ("Banque", json.dumps([{"index": 1, "propriete": "date"}]), json.dumps([])),
    )
    preset_id = curseur.lastrowid
    conn.commit()
    conn.close()
    return preset_id


def test_un_preset_existant_repart_sans_vocabulaire_declare(tmp_path):
    db_path = tmp_path / "sens_0027.db"
    _alembic(db_path, "upgrade", "0026")
    preset_id = _seed_preset(db_path)

    _alembic(db_path, "upgrade", "0027")

    conn = sqlite3.connect(db_path)
    sortie, entree = conn.execute(
        "SELECT libelles_sens_sortie, libelles_sens_entree FROM import_preset WHERE id = ?",
        (preset_id,),
    ).fetchone()
    # Vides = « celui du code », pas « aucun » : c'est ce qui garantit qu'un
    # preset existant lit son fichier exactement comme avant.
    assert json.loads(sortie) == []
    assert json.loads(entree) == []
    conn.close()


def test_downgrade_0027_retire_les_colonnes_sans_toucher_au_preset(tmp_path):
    db_path = tmp_path / "downgrade_0027.db"
    _alembic(db_path, "upgrade", "0026")
    _seed_preset(db_path)
    _alembic(db_path, "upgrade", "0027")

    _alembic(db_path, "downgrade", "0026")

    conn = sqlite3.connect(db_path)
    colonnes = {row[1] for row in conn.execute("PRAGMA table_info(import_preset)")}
    assert "libelles_sens_sortie" not in colonnes
    assert "libelles_sens_entree" not in colonnes
    assert conn.execute("SELECT nom FROM import_preset").fetchone()[0] == "Banque"
    conn.close()
