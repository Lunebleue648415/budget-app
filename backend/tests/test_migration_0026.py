"""La migration 0026 retire les formules et les colonnes supplémentaires d'un
preset d'import.

Ce qu'il s'agit de vérifier n'est pas la disparition des deux colonnes (une
ligne d'alembic) mais qu'elle ne coûte rien d'autre : la configuration de
colonnes du preset, ses correspondances mémorisées et son stock anti-doublons
doivent traverser la migration intacts. Un preset qui perdrait ses colonnes
réimporterait tout son historique en double au prochain fichier.
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

_COLONNES = [
    {"index": 1, "propriete": "date"},
    {"index": 2, "propriete": "nature"},
    {"index": 3, "propriete": "montant"},
    {"index": 4, "propriete": "monnaie"},
]


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
    """Un preset qui utilise VRAIMENT la configuration avancée d'avant : c'est
    le seul cas où la migration retire quelque chose."""
    conn = sqlite3.connect(db_path)
    curseur = conn.execute(
        """
        INSERT INTO import_preset (
            nom, colonnes, colonnes_exclues_comparaison, ignorer_premiere_ligne,
            colonnes_supplementaires, formules
        ) VALUES (?, ?, ?, 1, ?, ?)
        """,
        (
            "Wise",
            json.dumps(_COLONNES),
            json.dumps([12]),
            json.dumps([{"index": 5, "nom": "Frais source"}]),
            json.dumps({"montant": "=C3+C5", "montant_destination": "=C7", "frais": ""}),
        ),
    )
    preset_id = curseur.lastrowid
    conn.execute(
        "INSERT INTO import_categorie_mapping (preset_id, nom_banque, categorie_id) "
        "VALUES (?, ?, (SELECT id FROM categorie LIMIT 1))",
        (preset_id, "ABONNEMENTS"),
    )
    conn.commit()
    conn.close()
    return preset_id


def test_les_formules_et_colonnes_supplementaires_disparaissent(tmp_path):
    db_path = tmp_path / "avance_0026.db"
    _alembic(db_path, "upgrade", "0025")
    _seed_preset(db_path)

    _alembic(db_path, "upgrade", "0026")

    conn = sqlite3.connect(db_path)
    colonnes = {row[1] for row in conn.execute("PRAGMA table_info(import_preset)")}
    assert "formules" not in colonnes
    assert "colonnes_supplementaires" not in colonnes
    conn.close()


def test_le_reste_de_la_configuration_du_preset_survit(tmp_path):
    db_path = tmp_path / "survie_0026.db"
    _alembic(db_path, "upgrade", "0025")
    preset_id = _seed_preset(db_path)

    _alembic(db_path, "upgrade", "0026")

    conn = sqlite3.connect(db_path)
    nom, colonnes, exclues, entete = conn.execute(
        "SELECT nom, colonnes, colonnes_exclues_comparaison, ignorer_premiere_ligne "
        "FROM import_preset WHERE id = ?",
        (preset_id,),
    ).fetchone()
    assert nom == "Wise"
    assert json.loads(colonnes) == _COLONNES
    assert json.loads(exclues) == [12]
    assert entete == 1
    # Les correspondances mémorisées ne sont pas touchées : la colonne
    # `monnaie` reste lue, et leur perte redemanderait tout à l'utilisateur.
    assert (
        conn.execute(
            "SELECT count(*) FROM import_categorie_mapping WHERE preset_id = ?",
            (preset_id,),
        ).fetchone()[0]
        == 1
    )
    conn.close()


def test_downgrade_0026_rend_les_colonnes_vides(tmp_path):
    db_path = tmp_path / "downgrade_0026.db"
    _alembic(db_path, "upgrade", "0025")
    _seed_preset(db_path)
    _alembic(db_path, "upgrade", "0026")

    _alembic(db_path, "downgrade", "0025")

    conn = sqlite3.connect(db_path)
    colonnes_sup, formules = conn.execute(
        "SELECT colonnes_supplementaires, formules FROM import_preset"
    ).fetchone()
    # Rétablies, mais vides : les formules d'origine ne sont pas conservées.
    assert json.loads(colonnes_sup) == []
    assert json.loads(formules) == {}
    conn.close()
