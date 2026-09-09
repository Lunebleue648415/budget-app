"""La migration 0023 ajoute la configuration avancée des presets d'import.

Le point à vérifier est qu'elle est INERTE pour l'existant : un preset déjà
configuré doit continuer d'importer exactement comme avant, avec une
configuration avancée vide. Une valeur par défaut mal posée (NULL plutôt que
`[]`/`{}`) ferait planter la lecture du preset au premier import suivant.
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


def _seed_base_0022(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO import_preset (nom, colonnes, colonnes_exclues_comparaison, "
        "ignorer_premiere_ligne) VALUES ('Banque', ?, '[12]', 1)",
        (json.dumps(COLONNES),),
    )
    conn.commit()
    conn.close()


def test_un_preset_existant_survit_avec_une_configuration_avancee_vide(tmp_path):
    db_path = tmp_path / "repro_0023.db"
    _alembic(db_path, "upgrade", "0022")
    _seed_base_0022(db_path)

    _alembic(db_path, "upgrade", "0023")

    conn = sqlite3.connect(db_path)
    nom, colonnes, exclues, entete, supplementaires, formules = conn.execute(
        "select nom, colonnes, colonnes_exclues_comparaison, ignorer_premiere_ligne, "
        "colonnes_supplementaires, formules from import_preset where nom = 'Banque'"
    ).fetchone()

    # La configuration d'origine est intacte…
    assert json.loads(colonnes) == COLONNES
    assert json.loads(exclues) == [12]
    assert entete == 1
    # …et la configuration avancée est vide, pas NULL : le preset reste lisible
    # tel quel par l'app (cf. schemas.ImportPresetRead).
    assert json.loads(supplementaires) == []
    assert json.loads(formules) == {}
    conn.close()


def test_les_correspondances_de_monnaies_sont_scopees_par_preset(tmp_path):
    """Même règle que pour les catégories et les comptes : « EUR » peut
    légitimement désigner autre chose d'une banque à l'autre, et deux presets
    ne doivent jamais s'écraser."""
    db_path = tmp_path / "mappings_0023.db"
    _alembic(db_path, "upgrade", "0023")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO import_preset (nom, colonnes, colonnes_exclues_comparaison, "
        "ignorer_premiere_ligne, colonnes_supplementaires, formules) "
        "VALUES ('Wise', '[]', '[]', 0, '[]', '{}')"
    )
    presets = [r[0] for r in conn.execute("select id from import_preset order by id")]
    monnaie = conn.execute("select id from monnaie limit 1").fetchone()[0]

    for preset_id in presets:
        conn.execute(
            "INSERT INTO import_monnaie_mapping (preset_id, nom_banque, monnaie_id) "
            "VALUES (?, 'EUR', ?)",
            (preset_id, monnaie),
        )
    conn.commit()

    assert conn.execute("select count(*) from import_monnaie_mapping").fetchone()[0] == len(
        presets
    )

    # Unicité par (preset, libellé) : un même libellé ne peut pas viser deux
    # monnaies sous le même preset.
    try:
        conn.execute(
            "INSERT INTO import_monnaie_mapping (preset_id, nom_banque, monnaie_id) "
            "VALUES (?, 'EUR', ?)",
            (presets[0], monnaie),
        )
        assert False, "l'unicité (preset, nom_banque) n'est pas appliquée"
    except sqlite3.IntegrityError:
        pass
    conn.close()


def test_downgrade_0023_retire_la_configuration_avancee(tmp_path):
    db_path = tmp_path / "downgrade_0023.db"
    _alembic(db_path, "upgrade", "0022")
    _seed_base_0022(db_path)
    _alembic(db_path, "upgrade", "0023")

    _alembic(db_path, "downgrade", "0022")

    conn = sqlite3.connect(db_path)
    colonnes = {row[1] for row in conn.execute("PRAGMA table_info(import_preset)")}
    assert "colonnes_supplementaires" not in colonnes
    assert "formules" not in colonnes
    assert (
        conn.execute(
            "select count(*) from sqlite_master where type='table' "
            "and name='import_monnaie_mapping'"
        ).fetchone()[0]
        == 0
    )
    # Le preset lui-même, et sa configuration d'origine, survivent.
    assert conn.execute("select colonnes from import_preset where nom='Banque'").fetchone()[
        0
    ] == json.dumps(COLONNES)
    conn.close()
