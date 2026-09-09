"""PRÉVISUALISER AVEC DES COLONNES QUI NE SONT PAS CELLES DU PRESET.

À QUOI ÇA SERT : réorganiser les colonnes en déplaçant les en-têtes de l'aperçu
(ou en corrigeant leurs numéros) et VOIR ce que la lecture donne, avant de
décider d'enregistrer. Sans cela, il fallait enregistrer pour voir, donc écrire
dans le preset un arrangement qu'on n'a pas encore vérifié.

CE QUE CES TESTS PROTÈGENT, dans l'ordre de ce qui coûterait le plus cher :

  - LE PRESET N'EST PAS TOUCHÉ. Un essai qui modifierait les colonnes en base
    changerait la configuration de l'utilisateur parce qu'il a déplacé un
    en-tête pour regarder — et sans le lui dire ;
  - l'essai est vraiment pris en compte : lignes lues ET aperçu du fichier ;
  - sans essai, rien ne change : le preset décide, comme avant.
"""
import io

import openpyxl
import pytest
from fastapi import HTTPException

from app import crud, schemas
from app.routers import import_bancaire as routeur
from app.services import import_bancaire

from .conftest import creer_compte


# ---------- Outillage ----------


def _fichier(lignes):
    """Un classeur dont les colonnes sont, dans l'ordre : date, libellé,
    montant, catégorie."""
    classeur = openpyxl.Workbook()
    feuille = classeur.active
    for ligne in lignes:
        feuille.append(ligne)
    tampon = io.BytesIO()
    classeur.save(tampon)
    return tampon.getvalue()


CONTENU = _fichier(
    [
        ["05/09/2026", "COURSES SUPERETTE", -42.10, "Alimentation"],
        ["07/09/2026", "SALAIRE", 2400.00, "Revenus"],
    ]
)

# Le preset lit le libellé en colonne 4 et le montant en colonne 7 : deux
# colonnes que ce fichier n'a pas au bon endroit. C'est exactement le cas qu'on
# corrige en déplaçant les en-têtes.
COLONNES_DECALEES = [
    {"index": 1, "propriete": "date"},
    {"index": 4, "propriete": "nature"},
    {"index": 7, "propriete": "montant"},
]

COLONNES_JUSTES = [
    {"index": 1, "propriete": "date"},
    {"index": 2, "propriete": "nature"},
    {"index": 3, "propriete": "montant"},
    {"index": 4, "propriete": "categorie_banque"},
]


def _preset(db, compte):
    return crud.create_import_preset(
        db,
        "Ma banque",
        COLONNES_DECALEES,
        [],
        compte_id=compte.id,
    )


def _previsualiser(db, preset, colonnes=None):
    return import_bancaire.previsualiser(
        db, preset.id, CONTENU, colonnes=colonnes
    )


# ---------- Sans essai, le preset décide ----------


def test_sans_colonnes_le_preset_decide(db_session):
    compte = creer_compte(db_session, "Courant")
    preset = _preset(db_session, compte)

    apercu = _previsualiser(db_session, preset)

    # Colonne 4 = la catégorie du fichier, lue comme libellé ; pas de montant.
    assert apercu.lignes[0].nature == "Alimentation"
    assert apercu.lignes[0].montant is None


# ---------- Avec un essai, c'est l'essai qui décide ----------


def test_les_colonnes_de_l_essai_sont_lues(db_session):
    compte = creer_compte(db_session, "Courant")
    preset = _preset(db_session, compte)

    apercu = _previsualiser(db_session, preset, colonnes=COLONNES_JUSTES)

    assert [l.nature for l in apercu.lignes] == ["COURSES SUPERETTE", "SALAIRE"]
    assert [l.montant for l in apercu.lignes] == [42.10, 2400.00]
    assert [l.nom_banque_categorie for l in apercu.lignes] == ["Alimentation", "Revenus"]


def test_l_apercu_du_fichier_suit_l_essai(db_session):
    """Les couleurs et les en-têtes du tableau doivent décrire la lecture
    d'essai, sans quoi on corrigerait à l'aveugle."""
    compte = creer_compte(db_session, "Courant")
    preset = _preset(db_session, compte)

    apercu = _previsualiser(db_session, preset, colonnes=COLONNES_JUSTES)

    assert apercu.apercu_fichier.proprietes_par_colonne == {
        "1": "date",
        "2": "nature",
        "3": "montant",
        "4": "categorie_banque",
    }


# ---------- Le preset reste intact ----------


def test_le_preset_n_est_pas_modifie(db_session):
    """LE POINT DE TOUT LE RESTE : regarder ne doit rien écrire."""
    compte = creer_compte(db_session, "Courant")
    preset = _preset(db_session, compte)

    _previsualiser(db_session, preset, colonnes=COLONNES_JUSTES)
    db_session.commit()
    db_session.expire_all()

    assert crud.get_import_preset(db_session, preset.id).colonnes == COLONNES_DECALEES


def test_le_masque_laisse_passer_le_reste_du_preset(db_session):
    """Seules les colonnes sont remplacées : le compte lié, le vocabulaire et
    tout ce qui pend au preset doivent continuer de répondre."""
    compte = creer_compte(db_session, "Courant")
    preset = _preset(db_session, compte)
    masque = import_bancaire.PresetAvecColonnes(preset, COLONNES_JUSTES)

    assert masque.colonnes == COLONNES_JUSTES
    assert masque.id == preset.id
    assert masque.compte_id == compte.id
    assert masque.nom == "Ma banque"


# ---------- Ce que le routeur accepte ----------


def test_le_routeur_refuse_des_colonnes_illisibles():
    with pytest.raises(HTTPException) as erreur:
        routeur._valider_colonnes_essai("pas du json")
    assert erreur.value.status_code == 400


def test_le_routeur_refuse_une_propriete_inconnue():
    with pytest.raises(HTTPException) as erreur:
        routeur._valider_colonnes_essai(
            '{"colonnes": [{"index": 1, "propriete": "couleur_preferee"}]}'
        )
    assert erreur.value.status_code == 400


def test_le_routeur_rend_none_sans_colonnes():
    assert routeur._valider_colonnes_essai(None) is None


def test_le_routeur_rend_des_dicts_ordinaires():
    lues = routeur._valider_colonnes_essai(
        '{"colonnes": [{"index": 2, "propriete": "nature"}]}'
    )
    assert lues == [{"index": 2, "propriete": "nature"}]


# ---------- La confirmation lit les mêmes colonnes que l'aperçu ----------


def test_confirmer_suit_l_essai(db_session):
    """L'ÉCART QU'IL NE FAUT SURTOUT PAS OUVRIR : si l'aperçu lisait l'essai et
    la confirmation le preset, on importerait autre chose que ce qu'on vient de
    valider — et sans le moindre signe."""
    compte = creer_compte(db_session, "Courant")
    preset = _preset(db_session, compte)

    resultat = import_bancaire.confirmer(
        db_session,
        preset.id,
        CONTENU,
        schemas.ImportMappingOverrides(),
        colonnes=COLONNES_JUSTES,
    )

    assert resultat.operations_creees == 2
    operations = crud.get_operations(db_session)
    assert sorted(o.nature for o in operations) == ["COURSES SUPERETTE", "SALAIRE"]
    assert sorted(o.montant for o in operations) == [42.10, 2400.00]


def test_confirmer_ne_touche_pas_au_preset(db_session):
    compte = creer_compte(db_session, "Courant")
    preset = _preset(db_session, compte)

    import_bancaire.confirmer(
        db_session,
        preset.id,
        CONTENU,
        schemas.ImportMappingOverrides(),
        colonnes=COLONNES_JUSTES,
    )
    db_session.expire_all()

    assert crud.get_import_preset(db_session, preset.id).colonnes == COLONNES_DECALEES
