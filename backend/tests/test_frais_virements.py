"""LES FRAIS D'UN VIREMENT NE TRAVERSENT PAS : ils vont à la banque.

LE DÉFAUT QUE CES TESTS FERMENT, et qui se voyait sur le solde. Le relevé ne
décrit qu'UNE jambe d'un virement interne (c'est le relevé d'un seul compte) ;
l'autre était reprise telle quelle, FRAIS COMPRIS. Virer 100 € avec 2 € de frais
faisait donc perdre 102 € à l'émetteur et en faisait gagner 102 au récepteur :
les frais s'annulaient d'un compte à l'autre, et le total de l'app dépassait
celui de la banque de la somme de TOUS les frais de virement jamais importés —
un écart qui grandit à chaque import, sans que rien ne le signale.

L'INVARIANT, celui qu'on vérifie partout ici : un virement ne fait que déplacer
de l'argent, SEULS LES FRAIS COÛTENT. La variation du patrimoine doit donc valoir
exactement moins les frais, quel que soit le compte dont on importe le relevé.

Cf. services/import_bancaire._jambe_manquante.
"""
import io
from datetime import date

import openpyxl
import pytest

from app import crud, models, schemas
from app.constants import Sens
from app.services import import_bancaire

from .conftest import creer_compte, creer_monnaie, get_monnaie_id

# Un relevé ORDINAIRE, celui de la quasi-totalité des banques : une date, un
# libellé, un montant signé, des frais. Ni colonne « montant initial » (le
# relevé ne décrit qu'un côté), ni colonne de devise (tout est dans la monnaie
# du compte).
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
    """Seule une règle peut poser le type « virement interne » sur une ligne
    importée (cf. services/import_bancaire)."""
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


def _preset(db, compte, colonnes=None):
    return crud.create_import_preset(
        db,
        "Ma banque",
        colonnes or COLONNES,
        [],
        ignorer_premiere_ligne=False,
        compte_id=compte.id,
    )


def _importer(db, preset, lignes, autre=None):
    overrides = schemas.ImportMappingOverrides()
    if autre is not None:
        overrides = schemas.ImportMappingOverrides(
            lignes={1: schemas.ImportLigneOverride(compte_id_autre=autre.id)}
        )
    return import_bancaire.confirmer(db, preset.id, _fichier(lignes), overrides)


def _variation(db, monnaie_id=None):
    """Ce que le patrimoine gagne (+) ou perd (-) — la seule mesure qui compte
    ici, puisqu'un virement ne doit rien faire varier d'autre que ses frais."""
    total = 0.0
    for op in db.query(models.Operation).all():
        if monnaie_id is not None and op.monnaie_id != monnaie_id:
            continue
        if op.sens in (Sens.entree, Sens.transfert_entrant):
            total += op.montant
        else:
            total -= op.montant
    return total


def _jambes(db):
    sortante = db.query(models.Operation).filter_by(sens="transfert_sortant").one()
    entrante = db.query(models.Operation).filter_by(sens="transfert_entrant").one()
    return sortante, entrante


# ---------- Le relevé de l'émetteur ----------


def test_le_recepteur_recoit_le_vire_sans_les_frais(db_session):
    """LE CAS QUI A MOTIVÉ TOUT CECI. 100 € virés, 2 € de frais : l'émetteur
    perd 102, le récepteur gagne 100."""
    source = creer_compte(db_session, "Courant", solde_initial=1000.0)
    destination = creer_compte(db_session, "Livret")
    _regle_virement(db_session)
    preset = _preset(db_session, source)

    _importer(
        db_session,
        preset,
        [[date(2026, 7, 1), "Transfert vers Livret", -100.0, 2.0]],
        autre=destination,
    )

    sortante, entrante = _jambes(db_session)
    assert sortante.montant == pytest.approx(102.0)
    assert entrante.montant == pytest.approx(100.0)
    assert _variation(db_session) == pytest.approx(-2.0)


# ---------- Le relevé du récepteur ----------


def test_l_emetteur_a_envoye_le_recu_plus_les_frais(db_session):
    """Le relevé du compte qui REÇOIT : il annonce 100 € reçus et 2 € de frais,
    donc 98 réellement crédités — et 100 réellement partis d'en face."""
    destination = creer_compte(db_session, "Courant")
    source = creer_compte(db_session, "Livret", solde_initial=1000.0)
    _regle_virement(db_session)
    preset = _preset(db_session, destination)

    _importer(
        db_session,
        preset,
        [[date(2026, 7, 1), "Transfert depuis Livret", 100.0, 2.0]],
        autre=source,
    )

    sortante, entrante = _jambes(db_session)
    assert sortante.montant == pytest.approx(100.0)
    assert entrante.montant == pytest.approx(98.0)
    assert _variation(db_session) == pytest.approx(-2.0)


# ---------- Sans frais, rien ne change ----------


def test_sans_frais_les_deux_jambes_sont_egales(db_session):
    """Le comportement d'avant, qui était juste dans ce cas-là : sans frais, la
    jambe manquante vaut exactement l'autre."""
    source = creer_compte(db_session, "Courant", solde_initial=1000.0)
    destination = creer_compte(db_session, "Livret")
    _regle_virement(db_session)
    preset = _preset(db_session, source)

    _importer(
        db_session,
        preset,
        [[date(2026, 7, 1), "Transfert vers Livret", -100.0, None]],
        autre=destination,
    )

    sortante, entrante = _jambes(db_session)
    assert sortante.montant == entrante.montant == pytest.approx(100.0)
    assert _variation(db_session) == pytest.approx(0.0)


# ---------- Une dépense ordinaire n'est pas concernée ----------


def test_une_depense_ordinaire_sort_montant_plus_frais(db_session):
    """Un seul compte, une seule écriture : les frais s'ajoutent à ce qui part,
    et il n'y a aucune jambe à déduire."""
    compte = creer_compte(db_session, "Courant", solde_initial=1000.0)
    preset = _preset(db_session, compte)

    _importer(db_session, preset, [[date(2026, 7, 1), "Achat", -50.0, 3.0]])

    assert _variation(db_session) == pytest.approx(-53.0)


# ---------- Avec change, rien n'est déduit ----------


def test_avec_change_les_deux_jambes_viennent_du_fichier(db_session):
    """Entre deux monnaies, retrancher des frais à ce qui part ne dirait rien de
    ce qui arrive : il faudrait un taux, et l'app n'en connaît aucun. Le fichier
    donne donc les deux jambes, et les frais grèvent celle que leur devise
    désigne — ici l'émission : 100 € virés + 2 € de frais = 102 € partis."""
    euro = get_monnaie_id(db_session)
    dollar = creer_monnaie(db_session, "Dollar", "$").id
    source = creer_compte(db_session, "Wise EUR", monnaies=[(euro, 1000.0)])
    destination = creer_compte(db_session, "Wise USD", monnaies=[(dollar, 0.0)])
    _regle_virement(db_session)
    colonnes = COLONNES + [
        {"index": 5, "propriete": "monnaie"},
        {"index": 6, "propriete": "monnaie_frais"},
        {"index": 7, "propriete": "montant_initial"},
        {"index": 8, "propriete": "monnaie_initiale"},
        {"index": 9, "propriete": "sens"},
    ]
    preset = _preset(db_session, source, colonnes)
    for monnaie in crud.get_monnaies(db_session):
        crud.set_mapping_monnaie(db_session, preset.id, monnaie.nom, monnaie.id)

    _importer(
        db_session,
        preset,
        [
            [
                date(2026, 7, 1),
                "Transfert vers USD",
                108.0,
                2.0,
                "Dollar",
                "Euro",
                100.0,
                "Euro",
                "Débit",
            ]
        ],
        autre=destination,
    )

    sortante, entrante = _jambes(db_session)
    assert (sortante.montant, sortante.monnaie_id) == (pytest.approx(102.0), euro)
    assert (entrante.montant, entrante.monnaie_id) == (pytest.approx(108.0), dollar)
    # Chaque monnaie garde son propre compte : rien n'est additionné entre elles.
    assert _variation(db_session, euro) == pytest.approx(-102.0)
    assert _variation(db_session, dollar) == pytest.approx(108.0)


# ---------- La fonction elle-même ----------


def _ligne(**champs):
    base = dict(
        ligne=1,
        date=date(2026, 7, 1),
        nature="Transfert",
        type_code="virement",
        montant=None,
        montant_envoye=None,
        frais=None,
    )
    base.update(champs)
    return schemas.ImportLigne(**base)


def test_jambe_manquante_retranche_les_frais_a_ce_qui_part():
    envoye, recu = import_bancaire._jambe_manquante(
        _ligne(montant_envoye=102.0, frais=2.0), 102.0, None
    )
    assert (envoye, recu) == (pytest.approx(102.0), pytest.approx(100.0))


def test_jambe_manquante_ajoute_les_frais_a_ce_qui_arrive():
    envoye, recu = import_bancaire._jambe_manquante(
        _ligne(montant=98.0, frais=2.0), None, 98.0
    )
    assert (envoye, recu) == (pytest.approx(100.0), pytest.approx(98.0))


def test_jambe_manquante_ne_touche_a_rien_quand_les_deux_sont_connues():
    envoye, recu = import_bancaire._jambe_manquante(
        _ligne(montant_envoye=100.0, montant=108.0, frais=2.0), 100.0, 108.0
    )
    assert (envoye, recu) == (100.0, 108.0)


def test_jambe_manquante_ne_descend_jamais_sous_zero():
    """Ne peut pas arriver (le montant envoyé vaut toujours le hors-frais PLUS
    les frais), mais un virement à montant négatif serait refusé par
    VirementCreate avec un message incompréhensible."""
    envoye, recu = import_bancaire._jambe_manquante(
        _ligne(montant_envoye=1.0, frais=5.0), 1.0, None
    )
    assert recu == 0.0
