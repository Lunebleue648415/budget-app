"""Migration 0041 : le domaine d'un preset d'import, et le code ISIN d'un titre.

CE QUI COMPTE, ET POURQUOI C'EST TESTÉ PLUTÔT QUE SUPPOSÉ. La 0041 RECRÉE
`import_preset` (c'est le seul moyen, sous SQLite, de remplacer une contrainte
d'unicité implicite). Or cinq tables la référencent avec `ON DELETE CASCADE` :
si les migrations tournaient avec `PRAGMA foreign_keys` actif, le DROP de la
table d'origine emporterait au passage toutes les correspondances mémorisées,
tout l'historique d'imports et tout le stock anti-doublons de l'utilisateur.

Elles ne l'ont pas (alembic/env.py monte son propre moteur, sans le hook de
app/database.py) — mais « ne l'ont pas » est exactement le genre de propriété
qu'on veut voir vérifiée par un test plutôt que déduite d'une lecture.
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


def _preset_avec_tout_son_attirail(conn, nom: str) -> int:
    """Un preset et une ligne dans chacune de ses cinq tables filles."""
    conn.execute(
        "INSERT INTO import_preset (nom, colonnes, colonnes_comparaison) "
        "VALUES (?, '[]', '[]')",
        (nom,),
    )
    preset_id = conn.execute(
        "SELECT id FROM import_preset WHERE nom = ?", (nom,)
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO import_historique (preset_id, date_import, operations_creees, "
        "lignes_ignorees, doublons_detectes) VALUES (?, '2026-01-01', 3, 0, 0)",
        (preset_id,),
    )
    historique_id = conn.execute(
        "SELECT id FROM import_historique WHERE preset_id = ?", (preset_id,)
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO ligne_import_brute (preset_id, donnees, import_historique_id, "
        "date_creation) VALUES (?, '{\"1\": \"CARTE 12/01\"}', ?, '2026-01-01')",
        (preset_id, historique_id),
    )
    categorie_id = conn.execute("SELECT id FROM categorie LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO import_categorie_mapping (preset_id, nom_banque, categorie_id) "
        "VALUES (?, 'Alimentation', ?)",
        (preset_id, categorie_id),
    )
    monnaie_id = conn.execute("SELECT id FROM monnaie LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO import_monnaie_mapping (preset_id, nom_banque, monnaie_id) "
        "VALUES (?, 'EUR', ?)",
        (preset_id, monnaie_id),
    )
    conn.commit()
    return preset_id


def test_0041_la_recreation_de_la_table_ne_perd_aucune_donnee_fille(tmp_path):
    db_path = tmp_path / "r0041.db"
    _alembic(db_path, "upgrade", "0040")

    conn = sqlite3.connect(db_path)
    _preset_avec_tout_son_attirail(conn, "Ma banque")
    monnaie_id = conn.execute("SELECT id FROM monnaie LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO action (nom, valeur, monnaie_id) VALUES ('Air Liquide', 167.12, ?)",
        (monnaie_id,),
    )
    conn.commit()
    conn.close()

    _alembic(db_path, "upgrade", "0041")

    conn = sqlite3.connect(db_path)
    # TOUS les presets existants sont BANCAIRES : c'est ce qu'ils sont, et le
    # seul domaine qui existait avant cette migration. (« Défaut » est celui que
    # la migration 0014 sème dans toute base.)
    domaines = conn.execute("SELECT nom, domaine FROM import_preset").fetchall()
    assert ("Ma banque", "bancaire") in domaines
    assert {domaine for _, domaine in domaines} == {"bancaire"}
    # Les vocabulaires nouveaux sont vides, donc sans effet : un preset bancaire
    # ne lit pas la colonne « Type d'opération ».
    assert conn.execute(
        "SELECT libelles_type_achat, libelles_type_vente, libelles_type_transfert "
        "FROM import_preset WHERE nom = 'Ma banque'"
    ).fetchone() == ("[]", "[]", "[]")
    # LE POINT CENTRAL : les cinq tables filles ont survécu au DROP de la table
    # d'origine.
    for table in (
        "import_historique",
        "ligne_import_brute",
        "import_categorie_mapping",
        "import_monnaie_mapping",
    ):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1, table
    # Et le lien tient toujours : la ligne brute retrouve bien son preset.
    assert conn.execute(
        "SELECT p.nom FROM ligne_import_brute l "
        "JOIN import_preset p ON p.id = l.preset_id"
    ).fetchone() == ("Ma banque",)
    # Le titre existant est intact, sans ISIN — aucun n'est inventé.
    assert conn.execute("SELECT nom, valeur, code_isin FROM action").fetchone() == (
        "Air Liquide",
        167.12,
        None,
    )
    conn.close()


def test_0041_lunicite_du_nom_devient_composite(tmp_path):
    """« Boursorama » doit pouvoir désigner un relevé bancaire ET un relevé de
    compte-titres : ce sont deux formats sans rapport."""
    db_path = tmp_path / "u0041.db"
    _alembic(db_path, "upgrade", "0041")

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO import_preset (nom, domaine, colonnes, colonnes_comparaison) "
        "VALUES ('Boursorama', 'bancaire', '[]', '[]')"
    )
    conn.execute(
        "INSERT INTO import_preset (nom, domaine, colonnes, colonnes_comparaison) "
        "VALUES ('Boursorama', 'placement', '[]', '[]')"
    )
    conn.commit()

    # Le même nom DANS LE MÊME domaine reste refusé.
    try:
        conn.execute(
            "INSERT INTO import_preset (nom, domaine, colonnes, colonnes_comparaison) "
            "VALUES ('Boursorama', 'placement', '[]', '[]')"
        )
        raise AssertionError("un doublon (domaine, nom) aurait dû être refusé")
    except sqlite3.IntegrityError:
        pass
    conn.close()


def test_0041_un_isin_ne_peut_designer_quun_seul_titre(tmp_path):
    db_path = tmp_path / "i0041.db"
    _alembic(db_path, "upgrade", "0041")

    conn = sqlite3.connect(db_path)
    monnaie_id = conn.execute("SELECT id FROM monnaie LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO action (nom, valeur, monnaie_id, code_isin) "
        "VALUES ('Air Liquide', 167.0, ?, 'FR0000120073')",
        (monnaie_id,),
    )
    # Deux titres SANS ISIN ne se gênent pas : SQLite tolère autant de NULL
    # qu'on veut dans un index unique, et c'est le cas de tout titre saisi à la
    # main avant l'extension.
    conn.execute(
        "INSERT INTO action (nom, valeur, monnaie_id) VALUES ('Sans ISIN A', 1.0, ?)",
        (monnaie_id,),
    )
    conn.execute(
        "INSERT INTO action (nom, valeur, monnaie_id) VALUES ('Sans ISIN B', 1.0, ?)",
        (monnaie_id,),
    )
    conn.commit()

    try:
        conn.execute(
            "INSERT INTO action (nom, valeur, monnaie_id, code_isin) "
            "VALUES ('Air Liquide bis', 167.0, ?, 'FR0000120073')",
            (monnaie_id,),
        )
        raise AssertionError("un ISIN en double aurait dû être refusé")
    except sqlite3.IntegrityError:
        pass
    conn.close()


def test_0041_le_retour_arriere_ne_garde_que_le_bancaire(tmp_path):
    """Un preset de placements ne survit pas au retour arrière : ses colonnes
    désignent des propriétés que le code d'avant ne sait pas lire, et le laisser
    aurait mis dans le sélecteur de la page Import un format qui met toutes ses
    lignes en erreur. Les presets bancaires, eux, ne bougent pas."""
    db_path = tmp_path / "d0041.db"
    _alembic(db_path, "upgrade", "0041")

    conn = sqlite3.connect(db_path)
    _preset_avec_tout_son_attirail(conn, "Ma banque")
    conn.execute(
        "INSERT INTO import_preset (nom, domaine, colonnes, colonnes_comparaison) "
        "VALUES ('Mon courtier', 'placement', '[]', '[]')"
    )
    courtier_id = conn.execute(
        "SELECT id FROM import_preset WHERE nom = 'Mon courtier'"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO import_historique (preset_id, date_import, operations_creees, "
        "lignes_ignorees, doublons_detectes) VALUES (?, '2026-02-01', 5, 0, 0)",
        (courtier_id,),
    )
    conn.commit()
    conn.close()

    _alembic(db_path, "downgrade", "0040")

    conn = sqlite3.connect(db_path)
    noms = {nom for (nom,) in conn.execute("SELECT nom FROM import_preset")}
    assert "Ma banque" in noms
    assert "Mon courtier" not in noms
    # L'historique du courtier est parti avec lui ; celui de la banque reste.
    assert conn.execute(
        "SELECT COUNT(*) FROM import_historique"
    ).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM ligne_import_brute").fetchone()[0] == 1
    assert "code_isin" not in _colonnes(db_path, "action")
    assert "domaine" not in _colonnes(db_path, "import_preset")
    conn.close()
