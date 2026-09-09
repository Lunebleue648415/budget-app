"""LES FRAIS SURVIVENT À L'IMPORT (migration 0051).

CE QUI MANQUAIT. `_appliquer_frais` fondait les frais dans le montant — ajoutés
à ce qui sort, retranchés de ce qui entre — et ils disparaissaient. L'aperçu
d'import savait encore écrire « dont frais 2 € » ; l'opération enregistrée ne
portait plus qu'un montant de 102 € dont plus rien ne disait qu'il en contenait
2 de frais. Impossible de les relire, encore moins de les corriger.

CE QUE CES TESTS PROTÈGENT :

  - le montant NE CHANGE PAS. La colonne est purement descriptive : aucun solde,
    aucun KPI, aucune barre ne la lit. Si ajouter les frais avait fait bouger un
    montant, on aurait déplacé le problème au lieu de le résoudre ;
  - sur un virement, les frais ne sont portés que par UNE jambe — celle que leur
    devise désigne. Les inscrire des deux côtés les ferait lire deux fois ;
  - ils font l'aller-retour par les routes, sans quoi l'écran ne pourrait rien
    en montrer.
"""
import io
from datetime import date

import openpyxl
import pytest

from app import crud, models, schemas
from app.services import import_bancaire

from .conftest import creer_compte, creer_monnaie, get_monnaie_id, get_type_id

COLONNES = [
    {"index": 1, "propriete": "date"},
    {"index": 2, "propriete": "nature"},
    {"index": 3, "propriete": "montant"},
    {"index": 4, "propriete": "frais"},
]


def _fichier(lignes):
    classeur = openpyxl.Workbook()
    feuille = classeur.active
    for ligne in lignes:
        feuille.append(ligne)
    tampon = io.BytesIO()
    classeur.save(tampon)
    return tampon.getvalue()


def _regle_virement(db):
    return crud.create_regle_categorisation(
        db,
        nom="Transferts",
        type_id=db.query(models.TypeOperationDB).filter_by(code="virement").one().id,
        conditions={
            "operateur": "ET",
            "groupes": [
                {
                    "operateur": "ET",
                    "conditions": [
                        {"champ": "nature", "operateur": "contient", "valeur": "Transfert"}
                    ],
                }
            ],
        },
    )


def _importer(db, compte, lignes, autre=None, colonnes=None):
    preset = crud.create_import_preset(
        db,
        "Ma banque",
        colonnes or COLONNES,
        [],
        ignorer_premiere_ligne=False,
        compte_id=compte.id,
    )
    for monnaie in crud.get_monnaies(db):
        crud.set_mapping_monnaie(db, preset.id, monnaie.nom, monnaie.id)
    overrides = schemas.ImportMappingOverrides()
    if autre is not None:
        overrides = schemas.ImportMappingOverrides(
            lignes={1: schemas.ImportLigneOverride(compte_id_autre=autre.id)}
        )
    return import_bancaire.confirmer(db, preset.id, _fichier(lignes), overrides)


# ---------- Une opération ordinaire ----------


def test_une_depense_importee_garde_ses_frais(db_session):
    compte = creer_compte(db_session, "Courant", solde_initial=1000.0)

    _importer(db_session, compte, [[date(2026, 7, 1), "Achat", -50.0, 3.0]])

    operation = db_session.query(models.Operation).one()
    # Le montant reste ce qui a BOUGÉ sur le compte, frais compris.
    assert operation.montant == pytest.approx(53.0)
    assert operation.frais == pytest.approx(3.0)


def test_sans_frais_la_colonne_reste_nulle(db_session):
    """NULL et non zéro : « personne ne l'a renseigné » se distingue de « des
    frais de zéro », et c'est ce qui décide si l'écran montre la case."""
    compte = creer_compte(db_session, "Courant", solde_initial=1000.0)

    _importer(db_session, compte, [[date(2026, 7, 1), "Achat", -50.0, None]])

    assert db_session.query(models.Operation).one().frais is None


# ---------- Un virement ----------


def test_seule_la_jambe_grevee_porte_les_frais(db_session):
    """Les inscrire des deux côtés les ferait lire deux fois : le montant de
    chaque jambe les contient déjà, mais une seule les a subis."""
    source = creer_compte(db_session, "Courant", solde_initial=1000.0)
    destination = creer_compte(db_session, "Livret")
    _regle_virement(db_session)

    _importer(
        db_session,
        source,
        [[date(2026, 7, 1), "Transfert vers Livret", -100.0, 2.0]],
        autre=destination,
    )

    sortante = db_session.query(models.Operation).filter_by(sens="transfert_sortant").one()
    entrante = db_session.query(models.Operation).filter_by(sens="transfert_entrant").one()
    assert (sortante.montant, sortante.frais) == (pytest.approx(102.0), pytest.approx(2.0))
    assert (entrante.montant, entrante.frais) == (pytest.approx(100.0), None)


def test_la_devise_des_frais_designe_la_jambe(db_session):
    """Des frais dans la monnaie REÇUE grèvent ce qui arrive, pas ce qui part."""
    euro = get_monnaie_id(db_session)
    dollar = creer_monnaie(db_session, "Dollar", "$").id
    source = creer_compte(db_session, "Courant", monnaies=[(euro, 1000.0)])
    destination = creer_compte(db_session, "Compte USD", monnaies=[(dollar, 0.0)])

    virement = crud.create_virement(
        db_session,
        schemas.VirementCreate(
            date=date(2026, 7, 1),
            compte_source_id=source.id,
            compte_destination_id=destination.id,
            montant=100.0,
            monnaie_id=euro,
            montant_destination=106.0,
            monnaie_destination_id=dollar,
            frais=2.0,
            monnaie_frais_id=dollar,
        ),
        source,
        destination,
    )

    sortante, entrante = virement
    assert sortante.frais is None
    assert entrante.frais == pytest.approx(2.0)
    assert entrante.monnaie_frais_id == dollar


def test_modifier_un_virement_deplace_les_frais_sans_les_dupliquer(db_session):
    """La jambe grevée peut changer avec la devise des frais : l'autre doit être
    nettoyée, sinon les frais resteraient inscrits des deux côtés."""
    euro = get_monnaie_id(db_session)
    dollar = creer_monnaie(db_session, "Dollar", "$").id
    source = creer_compte(db_session, "Courant", monnaies=[(euro, 1000.0)])
    destination = creer_compte(db_session, "Compte USD", monnaies=[(dollar, 0.0)])

    def payload(monnaie_frais):
        return schemas.VirementCreate(
            date=date(2026, 7, 1),
            compte_source_id=source.id,
            compte_destination_id=destination.id,
            montant=100.0,
            monnaie_id=euro,
            montant_destination=106.0,
            monnaie_destination_id=dollar,
            frais=2.0,
            monnaie_frais_id=monnaie_frais,
        )

    sortante, entrante = crud.create_virement(
        db_session, payload(euro), source, destination
    )
    assert (sortante.frais, entrante.frais) == (pytest.approx(2.0), None)

    crud.update_virement(
        db_session, [sortante, entrante], payload(dollar), source, destination
    )
    db_session.refresh(sortante)
    db_session.refresh(entrante)
    assert (sortante.frais, entrante.frais) == (None, pytest.approx(2.0))


# ---------- L'aller-retour par les routes ----------


def test_les_frais_se_lisent_et_s_ecrivent_par_operations(db_session):
    compte = creer_compte(db_session, "Courant", solde_initial=1000.0)
    from .conftest import get_categorie_id

    operation = crud.create_operation(
        db_session,
        schemas.OperationCreate(
            date=date(2026, 7, 1),
            compte_id=compte.id,
            monnaie_id=get_monnaie_id(db_session),
            type_id=get_type_id(db_session, "classique"),
            categorie_id=get_categorie_id(db_session, "Alimentaire"),
            nature="Retrait à l'étranger",
            montant=53.0,
            frais=3.0,
            statut="réel",
        ),
    )
    assert operation.frais == pytest.approx(3.0)

    lue = schemas.OperationRead.model_validate(operation)
    assert lue.frais == pytest.approx(3.0)

    crud.update_operation(
        db_session, operation, schemas.OperationUpdate(frais=5.0, montant=55.0)
    )
    db_session.refresh(operation)
    assert (operation.montant, operation.frais) == (pytest.approx(55.0), pytest.approx(5.0))


def test_les_frais_ne_changent_aucun_solde(db_session):
    """LA GARANTIE DE FOND : la colonne est descriptive. Deux opérations
    identiques, l'une annotée de frais, doivent donner le même solde."""
    from app.services import soldes

    compte = creer_compte(db_session, "Courant", solde_initial=1000.0)
    from .conftest import get_categorie_id

    def depense(frais):
        return crud.create_operation(
            db_session,
            schemas.OperationCreate(
                date=date(2026, 7, 1),
                compte_id=compte.id,
                monnaie_id=get_monnaie_id(db_session),
                type_id=get_type_id(db_session, "classique"),
                categorie_id=get_categorie_id(db_session, "Alimentaire"),
                nature="Achat",
                montant=53.0,
                frais=frais,
                statut="réel",
            ),
        )

    depense(None)
    avant = soldes.get_soldes_comptes(db_session)[0]["soldes"][
        get_monnaie_id(db_session)
    ]["solde_reel"]
    depense(3.0)
    apres = soldes.get_soldes_comptes(db_session)[0]["soldes"][
        get_monnaie_id(db_session)
    ]["solde_reel"]

    # Les deux dépenses valent 53 € : la seconde n'a rien coûté de plus parce
    # qu'elle porte l'annotation.
    assert avant - apres == pytest.approx(53.0)
