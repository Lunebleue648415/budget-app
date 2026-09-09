"""La migration 0028 ajoute le vocabulaire de la colonne « État ».

Même exigence que la 0027 : elle n'active rien. Un preset existant repart avec
trois listes VIDES, ce qui veut dire « le vocabulaire du code », et comme il ne
lit pas la colonne « État », toutes ses lignes restent des opérations réelles.
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

_COLONNES = (
    "libelles_statut_execute",
    "libelles_statut_attente",
    "libelles_statut_refuse",
)


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


def test_un_preset_existant_repart_sans_vocabulaire_detat(tmp_path):
    db_path = tmp_path / "statut_0028.db"
    _alembic(db_path, "upgrade", "0027")
    preset_id = _seed_preset(db_path)

    _alembic(db_path, "upgrade", "0028")

    conn = sqlite3.connect(db_path)
    valeurs = conn.execute(
        f"SELECT {', '.join(_COLONNES)} FROM import_preset WHERE id = ?", (preset_id,)
    ).fetchone()
    assert [json.loads(v) for v in valeurs] == [[], [], []]
    conn.close()


def test_downgrade_0028_retire_les_colonnes_sans_toucher_au_preset(tmp_path):
    db_path = tmp_path / "downgrade_0028.db"
    _alembic(db_path, "upgrade", "0027")
    _seed_preset(db_path)
    _alembic(db_path, "upgrade", "0028")

    _alembic(db_path, "downgrade", "0027")

    conn = sqlite3.connect(db_path)
    colonnes = {row[1] for row in conn.execute("PRAGMA table_info(import_preset)")}
    assert not (colonnes & set(_COLONNES))
    assert conn.execute("SELECT nom FROM import_preset").fetchone()[0] == "Banque"
    conn.close()
