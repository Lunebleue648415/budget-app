"""La migration 0024 lie un preset d'import à un compte bancaire.

Deux points à vérifier : qu'elle est INERTE pour l'existant (un preset déjà
configuré reste non lié, donc importe exactement comme avant), et que
supprimer le compte lié ne détruit pas le preset — son format de colonnes, son
historique et son stock anti-doublons n'ont rien à voir avec l'existence du
compte, d'où le ON DELETE SET NULL.
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


COLONNES = [
    {"index": 1, "propriete": "date"},
    {"index": 4, "propriete": "nature"},
    {"index": 7, "propriete": "montant"},
]


def _seed_preset(conn, nom="Banque"):
    conn.execute(
        "INSERT INTO import_preset (nom, colonnes, colonnes_exclues_comparaison, "
        "ignorer_premiere_ligne, colonnes_supplementaires, formules) "
        "VALUES (?, ?, '[]', 0, '[]', '{}')",
        (nom, json.dumps(COLONNES)),
    )


def _seed_compte(conn, nom="Courant"):
    type_id = conn.execute("select id from type_compte limit 1").fetchone()[0]
    curseur = conn.execute(
        "INSERT INTO compte (nom, type_id) VALUES (?, ?)", (nom, type_id)
    )
    return curseur.lastrowid


def test_un_preset_existant_reste_non_lie(tmp_path):
    db_path = tmp_path / "repro_0024.db"
    _alembic(db_path, "upgrade", "0023")
    conn = sqlite3.connect(db_path)
    _seed_preset(conn)
    conn.commit()
    conn.close()

    _alembic(db_path, "upgrade", "0024")

    conn = sqlite3.connect(db_path)
    colonnes, compte_id = conn.execute(
        "select colonnes, compte_id from import_preset where nom = 'Banque'"
    ).fetchone()
    assert json.loads(colonnes) == COLONNES
    # NULL, pas 0 : le compte continue de venir du fichier, comme avant.
    assert compte_id is None
    conn.close()


def test_supprimer_le_compte_lie_delie_le_preset_sans_le_detruire(tmp_path):
    db_path = tmp_path / "cascade_0024.db"
    _alembic(db_path, "upgrade", "0024")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    compte_id = _seed_compte(conn)
    _seed_preset(conn)
    conn.execute(
        "UPDATE import_preset SET compte_id = ? WHERE nom = 'Banque'", (compte_id,)
    )
    conn.commit()

    conn.execute("DELETE FROM compte WHERE id = ?", (compte_id,))
    conn.commit()

    nom, lie = conn.execute(
        "select nom, compte_id from import_preset where nom = 'Banque'"
    ).fetchone()
    assert nom == "Banque"
    assert lie is None
    conn.close()


def test_downgrade_0024_retire_la_liaison(tmp_path):
    db_path = tmp_path / "downgrade_0024.db"
    _alembic(db_path, "upgrade", "0024")
    conn = sqlite3.connect(db_path)
    compte_id = _seed_compte(conn)
    _seed_preset(conn)
    conn.execute(
        "UPDATE import_preset SET compte_id = ? WHERE nom = 'Banque'", (compte_id,)
    )
    conn.commit()
    conn.close()

    _alembic(db_path, "downgrade", "0023")

    conn = sqlite3.connect(db_path)
    colonnes = {row[1] for row in conn.execute("PRAGMA table_info(import_preset)")}
    assert "compte_id" not in colonnes
    # Le preset et sa configuration d'origine survivent.
    assert conn.execute("select colonnes from import_preset where nom='Banque'").fetchone()[
        0
    ] == json.dumps(COLONNES)
    conn.close()
