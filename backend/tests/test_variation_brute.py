"""La VARIATION BRUTE : ce qui est passé sur les comptes courants du mois.

DEUX QUESTIONS, DEUX CHIFFRES, et tout l'enjeu est de ne pas les confondre :

  - « qu'est-ce que ce mois me coûte » — c'est `get_flux_periode`, qui étale les
    dépenses amorties, retranche ce qu'on nous rendra d'une dépense remboursable
    et écarte les règlements ;
  - « de combien le compte a bougé » — c'est `get_variation_brute`, qui ne fait
    rien de tout cela. Le montant tel qu'il est, à la date où il est.

Les tests ci-dessous vérifient chacun des écarts entre les deux, un par un.
"""
from datetime import date

import pytest

from app import crud, schemas
from app.constants import Sens, Statut
from app.services import soldes

from .conftest import creer_compte, get_categorie_id, get_monnaie_id, get_type_id


def _op(db, compte, montant, jour=10, sens=Sens.depense, type_code="classique", **kwargs):
    defaults = dict(
        date=date(2026, 1, jour),
        compte_id=compte.id,
        monnaie_id=get_monnaie_id(db),
        type_id=get_type_id(db, type_code),
        categorie_id=get_categorie_id(db, "Alimentaire"),
        nature="Ligne",
        montant=montant,
        sens=sens,
        statut=Statut.reel,
    )
    defaults.update(kwargs)
    return crud.create_operation(db, schemas.OperationCreate(**defaults))


def _brute(db, annee=2026, mois=1):
    return soldes.get_variation_brute(db, annee, mois, get_monnaie_id(db))


def _flux(db, annee=2026, mois=1):
    return soldes.get_flux_periode(db, annee, mois, get_monnaie_id(db))["variation"]


# ---------- Le cas ordinaire ----------


def test_entrees_moins_sorties(db_session):
    compte = creer_compte(db_session, "Courant")
    _op(db_session, compte, 2000.0, jour=1, sens=Sens.entree,
        categorie_id=get_categorie_id(db_session, "Entrées d'argent"))
    _op(db_session, compte, 300.0, jour=5)
    _op(db_session, compte, 120.0, jour=20)

    assert _brute(db_session) == pytest.approx(1580.0)


def test_le_previsionnel_compte_comme_le_reel(db_session):
    """Une opération à venir dans le mois en fait partie : c'est la même règle
    que pour les flux."""
    compte = creer_compte(db_session, "Courant")
    _op(db_session, compte, 100.0, statut=Statut.previsionnel)
    assert _brute(db_session) == pytest.approx(-100.0)


# ---------- Les trois écarts avec les flux ----------


def test_une_depense_amortie_compte_en_entier_au_mois_de_sa_date(db_session):
    """L'étalement dit ce qu'une facture PÈSE, pas ce qui a quitté le compte."""
    compte = creer_compte(db_session, "Courant")
    _op(
        db_session,
        compte,
        1200.0,
        amorti=True,
        amortissement_debut=date(2026, 1, 1),
        amortissement_fin=date(2026, 12, 1),
    )

    assert _brute(db_session) == pytest.approx(-1200.0)
    # Les flux, eux, n'en imputent qu'un douzième au mois.
    assert _flux(db_session) == pytest.approx(-100.0)


def test_une_depense_remboursable_compte_pour_son_montant_entier(db_session):
    """L'argent est parti, même s'il reviendra."""
    compte = creer_compte(db_session, "Courant")
    _op(db_session, compte, 200.0, type_code="remboursable", montant_du=150.0)

    assert _brute(db_session) == pytest.approx(-200.0)
    # Les flux ne comptent que ce qui reste à ma charge.
    assert _flux(db_session) == pytest.approx(-50.0)


def test_un_reglement_recu_compte_alors_que_les_flux_l_ecartent(db_session):
    """Un remboursement solde une dette déjà comptée — mais il fait bel et bien
    entrer de l'argent sur le compte."""
    compte = creer_compte(db_session, "Courant")
    _op(
        db_session,
        compte,
        80.0,
        sens=Sens.entree,
        type_code="remboursements",
        categorie_id=None,
    )

    assert _brute(db_session) == pytest.approx(80.0)
    assert _flux(db_session) == pytest.approx(0.0)


def test_un_pret_recu_compte_pour_son_montant_entier(db_session):
    """Cet argent est arrivé, même s'il faudra le rendre. Les flux, eux, n'en
    retiennent que les intérêts, et du côté des sorties."""
    compte = creer_compte(db_session, "Courant")
    _op(
        db_session,
        compte,
        1000.0,
        sens=Sens.entree,
        type_code="pret",
        categorie_id=None,
        montant_du=1050.0,
    )

    assert _brute(db_session) == pytest.approx(1000.0)
    assert _flux(db_session) == pytest.approx(-50.0)


# ---------- Ce qui reste écarté ----------


def test_un_virement_interne_ne_bouge_rien(db_session):
    """Déplacer de l'argent entre ses propres comptes ne fait varier aucun
    total."""
    source = creer_compte(db_session, "Courant")
    cible = creer_compte(db_session, "Autre courant")
    crud.create_virement(
        db_session,
        schemas.VirementCreate(
            date=date(2026, 1, 12),
            compte_source_id=source.id,
            compte_destination_id=cible.id,
            monnaie_id=get_monnaie_id(db_session),
            montant=500.0,
            statut=Statut.reel,
        ),
        source,
        cible,
    )

    assert _brute(db_session) == pytest.approx(0.0)


def test_les_comptes_d_epargne_sont_hors_perimetre(db_session):
    """Même périmètre que le « Solde total » posé à côté, qui les exclut : les
    deux chiffres doivent parler des mêmes comptes."""
    epargne = creer_compte(db_session, "Livret", type_nom="épargne")
    _op(db_session, epargne, 400.0, sens=Sens.entree,
        categorie_id=get_categorie_id(db_session, "Entrées d'argent"))

    assert _brute(db_session) == pytest.approx(0.0)


def test_un_autre_mois_n_entre_pas(db_session):
    compte = creer_compte(db_session, "Courant")
    _op(db_session, compte, 90.0, date=date(2026, 2, 3))
    assert _brute(db_session) == pytest.approx(0.0)
    assert _brute(db_session, mois=2) == pytest.approx(-90.0)


def test_la_vue_annuelle_somme_les_douze_mois(db_session):
    compte = creer_compte(db_session, "Courant")
    _op(db_session, compte, 90.0, date=date(2026, 2, 3))
    _op(db_session, compte, 10.0, date=date(2026, 7, 3))
    assert soldes.get_variation_brute(db_session, 2026, None, get_monnaie_id(db_session)) == (
        pytest.approx(-100.0)
    )


def test_une_autre_monnaie_n_entre_pas(db_session):
    from .conftest import creer_monnaie

    dollar = creer_monnaie(db_session, "Dollar", "$")
    compte = creer_compte(
        db_session,
        "Courant",
        monnaies=[(get_monnaie_id(db_session), 0.0), (dollar.id, 0.0)],
    )
    _op(db_session, compte, 50.0, monnaie_id=dollar.id)

    assert _brute(db_session) == pytest.approx(0.0)
    assert soldes.get_variation_brute(db_session, 2026, 1, dollar.id) == pytest.approx(-50.0)
