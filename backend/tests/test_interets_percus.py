"""Intérêts perçus (extension « Intérêts perçus »).

Ce que ces tests protègent, dans l'ordre de ce qui coûterait le plus cher à
casser :

  - RIEN N'EST ÉCRIT EN OPÉRATIONS. C'est la promesse de l'extension : saisir
    ce qu'un livret a rapporté ne doit toucher ni les soldes, ni les flux, ni
    quoi que ce soit d'autre. Si ça cassait, un montant serait compté deux fois
    — une fois ici, une fois par l'import du relevé qui le porte — et le total
    de l'app cesserait de correspondre à celui de la banque ;
  - LES MONNAIES NE S'ADDITIONNENT JAMAIS. Un compte multi-devises rend un total
    PAR devise. Additionner reviendrait à inventer un taux de change, ce que
    l'application ne fait nulle part ;
  - LES GARDES. Seuls les comptes d'épargne, seules les monnaies du compte,
    seuls les montants strictement positifs. Chacun protège d'un chiffre affiché
    que rien ne pourrait expliquer.
"""
from datetime import date

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import models

from .conftest import (
    charger_module_extension,
    creer_compte,
    creer_monnaie,
    get_monnaie_id,
)

service = charger_module_extension("interets-percus", "service_interets.py")
routeur = charger_module_extension("interets-percus", "routeur_interets.py")
schemas_ip = charger_module_extension("interets-percus", "schemas_interets.py")


# ---------- Outillage ----------


def _livret(db, nom="Livret A", solde_initial=0.0, monnaies=None):
    return creer_compte(db, nom, type_nom="épargne", solde_initial=solde_initial, monnaies=monnaies)


def _verser(db, compte, montant, jour=date(2026, 1, 31), monnaie_id=None, libelle=""):
    return service.creer_interet(
        db,
        compte_id=compte.id,
        monnaie_id=monnaie_id or compte.monnaie_principale_id,
        date=jour,
        montant=montant,
        libelle=libelle,
    )


# ---------- La promesse : rien n'est écrit ----------


def test_saisir_des_interets_ne_cree_aucune_operation(db_session):
    """LA garantie de l'extension. Un intérêt saisi ici et le même intérêt
    importé depuis le relevé feraient sinon deux fois le même montant."""
    compte = _livret(db_session, solde_initial=1000.0)
    _verser(db_session, compte, 42.0)

    assert db_session.query(models.Operation).count() == 0


def test_saisir_des_interets_ne_touche_pas_au_solde(db_session):
    from app.services import soldes

    compte = _livret(db_session, solde_initial=1000.0)
    monnaie_id = get_monnaie_id(db_session)
    avant = soldes.get_soldes_comptes(db_session)
    _verser(db_session, compte, 42.0)
    apres = soldes.get_soldes_comptes(db_session)

    def solde_reel(etat):
        item = next(i for i in etat if i["compte"].id == compte.id)
        return item["soldes"][monnaie_id]["solde_reel"]

    assert solde_reel(apres) == solde_reel(avant) == 1000.0


# ---------- Les totaux ----------


def test_le_total_additionne_les_versements_du_compte(db_session):
    compte = _livret(db_session)
    _verser(db_session, compte, 12.5, date(2026, 1, 31))
    _verser(db_session, compte, 20.0, date(2026, 6, 30))

    lu = routeur._lire_compte(db_session, compte)
    assert [(t.monnaie_id, t.montant) for t in lu.totaux] == [(compte.monnaie_principale_id, 32.5)]


def test_les_totaux_se_font_par_annee_de_la_plus_recente_a_la_plus_ancienne(db_session):
    """PAR ANNÉE parce que c'est le rythme auquel une banque verse et annonce
    ses intérêts : c'est la seule comparaison qui veuille dire quelque chose."""
    compte = _livret(db_session)
    _verser(db_session, compte, 96.0, date(2025, 12, 31))
    _verser(db_session, compte, 100.0, date(2026, 6, 30))
    _verser(db_session, compte, 42.0, date(2026, 12, 31))

    lu = routeur._lire_compte(db_session, compte)
    assert [(a.annee, a.totaux[0].montant) for a in lu.annees] == [(2026, 142.0), (2025, 96.0)]


def test_deux_monnaies_ne_sont_jamais_additionnees(db_session):
    """L'app ne connaît aucun taux de change : un compte multi-devises rend un
    total par devise, jamais un total tout court."""
    euro = get_monnaie_id(db_session)
    dollar = creer_monnaie(db_session, "Dollar", "$").id
    compte = _livret(db_session, monnaies=[(euro, 0.0), (dollar, 0.0)])
    _verser(db_session, compte, 30.0, monnaie_id=euro)
    _verser(db_session, compte, 45.0, monnaie_id=dollar)

    lu = routeur._lire_compte(db_session, compte)
    par_monnaie = {t.monnaie_id: t.montant for t in lu.totaux}
    assert par_monnaie == {euro: 30.0, dollar: 45.0}


def test_les_versements_sont_rendus_du_plus_recent_au_plus_ancien(db_session):
    compte = _livret(db_session)
    _verser(db_session, compte, 10.0, date(2024, 12, 31))
    _verser(db_session, compte, 20.0, date(2026, 12, 31))
    _verser(db_session, compte, 15.0, date(2025, 12, 31))

    dates = [i.date for i in service.interets_du_compte(db_session, compte.id)]
    assert dates == [date(2026, 12, 31), date(2025, 12, 31), date(2024, 12, 31)]


# ---------- Les gardes ----------


def test_seuls_les_comptes_d_epargne_sont_proposes(db_session):
    """Un compte courant ne verse pas d'intérêts, et un compte-titres se
    valorise à son cours — pas en encaissant des intérêts."""
    _livret(db_session, "Livret A")
    creer_compte(db_session, "Compte courant", type_nom="courant")

    assert [c.nom for c in service.comptes_epargne(db_session)] == ["Livret A"]


def test_un_compte_qui_n_est_pas_d_epargne_est_refuse(db_session):
    courant = creer_compte(db_session, "Compte courant", type_nom="courant")
    with pytest.raises(HTTPException) as erreur:
        routeur._get_compte_epargne_ou_404(db_session, courant.id)
    assert erreur.value.status_code == 404


def test_une_monnaie_etrangere_au_compte_est_refusee(db_session):
    """Sans ce contrôle, un total afficherait une devise que le compte ne peut
    pas porter, et personne ne saurait d'où elle sort."""
    dollar = creer_monnaie(db_session, "Dollar", "$").id
    compte = _livret(db_session)  # en euros seulement

    with pytest.raises(HTTPException) as erreur:
        routeur._valider_monnaie(compte, dollar)
    assert erreur.value.status_code == 400


def test_sans_monnaie_precisee_on_prend_la_principale_du_compte(db_session):
    """Presque tous les livrets sont mono-devises : leur demander de choisir
    serait un champ à traverser pour rien."""
    compte = _livret(db_session)
    assert routeur._valider_monnaie(compte, None) == compte.monnaie_principale_id


@pytest.mark.parametrize("montant", [0, -5])
def test_un_montant_nul_ou_negatif_est_refuse(montant):
    """Un intérêt PERÇU est une entrée : zéro se dit en ne saisissant rien, et
    un négatif serait des frais — qui sont des opérations ordinaires."""
    with pytest.raises(ValidationError):
        schemas_ip.InteretCreate(date=date(2026, 1, 31), montant=montant)


# ---------- Retouche et suppression ----------


def test_modifier_n_ecrase_que_les_champs_fournis(db_session):
    """`None` veut dire « ne change pas », jamais « efface » — la règle de toute
    l'application."""
    compte = _livret(db_session)
    interet = _verser(db_session, compte, 42.0, libelle="intérêts 2025")

    service.modifier_interet(db_session, interet, montant=50.0, libelle=None)
    assert (interet.montant, interet.libelle) == (50.0, "intérêts 2025")


def test_supprimer_un_versement_le_retire_des_totaux(db_session):
    compte = _livret(db_session)
    garde = _verser(db_session, compte, 10.0)
    retire = _verser(db_session, compte, 90.0)

    service.supprimer_interet(db_session, retire)
    lu = routeur._lire_compte(db_session, compte)
    assert [i.id for i in lu.interets] == [garde.id]
    assert lu.totaux[0].montant == 10.0


def test_supprimer_le_compte_emporte_ses_interets(db_session):
    """CASCADE : une ligne d'intérêts ne décrit rien sans son compte, et
    orpheline elle ne serait plus rattachable à quoi que ce soit."""
    from app import crud

    compte = _livret(db_session)
    _verser(db_session, compte, 42.0)
    crud.delete_compte(db_session, compte)

    assert db_session.query(models.InteretPercu).count() == 0
