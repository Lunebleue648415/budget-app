"""UN VIREMENT EST INDIVISIBLE devant les filtres de la page Opérations.

LE BUG QUE CES TESTS FERMENT. Ses deux écritures ne sont pas deux opérations qui
se ressemblent : c'est UN mouvement décrit des deux côtés. Or aucun filtre ne
s'applique pareil aux deux — filtrer sur le compte émetteur ne retenait que sa
jambe, filtrer sur un montant ne retenait qu'un côté d'un virement avec change.
L'écran recevait donc une moitié de virement et l'affichait comme un virement à
qui il MANQUE UN COMPTE, en proposant de le supprimer et de le recréer. Le
virement, lui, était parfaitement complet en base.

`paires_virement=True` ramène la jambe manquante. Le drapeau est POSÉ PAR
L'ÉCRAN OPÉRATIONS et par lui seul : les autres lecteurs de `/operations`
listent des opérations, pas des virements, et une jambe hors filtre n'a rien à
faire dans leur liste — c'est ce que vérifie la dernière section.
"""
from datetime import date

from app import crud, schemas
from app.constants import Sens, Statut

from .conftest import creer_compte, creer_monnaie, get_monnaie_id


def _virement(db, source, destination, montant=250.0, jour=15, **kwargs):
    defaults = dict(
        date=date(2026, 9, jour),
        compte_source_id=source.id,
        compte_destination_id=destination.id,
        montant=montant,
        monnaie_id=get_monnaie_id(db),
        nature="Mise de côté",
        statut=Statut.reel,
    )
    defaults.update(kwargs)
    return crud.create_virement(
        db, schemas.VirementCreate(**defaults), source, destination
    )


def _deux_comptes(db):
    return creer_compte(db, "Courant"), creer_compte(db, "Voyage")


def _jambes(operations):
    return {(op.compte_id, op.sens) for op in operations if op.virement_id is not None}


# ---------- Le filtre de compte ----------


def test_filtrer_sur_un_compte_ramene_les_deux_jambes(db_session):
    """LE CAS QUI A MOTIVÉ TOUT CECI : filtrer sur le compte émetteur."""
    source, destination = _deux_comptes(db_session)
    _virement(db_session, source, destination)

    operations = crud.get_operations(
        db_session, compte_id=source.id, paires_virement=True
    )

    assert _jambes(operations) == {
        (source.id, Sens.transfert_sortant),
        (destination.id, Sens.transfert_entrant),
    }


def test_filtrer_sur_le_compte_recepteur_ramene_aussi_les_deux(db_session):
    source, destination = _deux_comptes(db_session)
    _virement(db_session, source, destination)

    operations = crud.get_operations(
        db_session, compte_id=destination.id, paires_virement=True
    )

    assert len([op for op in operations if op.virement_id is not None]) == 2


def test_sans_le_drapeau_le_filtre_coupe_le_virement(db_session):
    """Le comportement d'avant, conservé pour les autres lecteurs de la route :
    ils lisent des opérations, pas des virements."""
    source, destination = _deux_comptes(db_session)
    _virement(db_session, source, destination)

    operations = crud.get_operations(db_session, compte_id=source.id)

    assert _jambes(operations) == {(source.id, Sens.transfert_sortant)}


# ---------- Les autres filtres ----------


def test_un_filtre_de_montant_ramene_la_jambe_d_un_autre_montant(db_session):
    """Un virement AVEC CHANGE porte deux montants : borner le montant ne
    retenait qu'un côté."""
    dollar = creer_monnaie(db_session, "Dollar", "$")
    source = creer_compte(db_session, "Courant")
    destination = creer_compte(
        db_session, "Compte USD", monnaies=[(dollar.id, 0.0)]
    )
    _virement(
        db_session,
        source,
        destination,
        montant=100.0,
        monnaie_destination_id=dollar.id,
        montant_destination=110.0,
    )

    operations = crud.get_operations(
        db_session, montant_min=95.0, montant_max=105.0, paires_virement=True
    )

    montants = sorted(op.montant for op in operations if op.virement_id is not None)
    assert montants == [100.0, 110.0]


def test_un_filtre_de_categorie_n_invente_pas_de_virement(db_session):
    """Un virement ne porte pas de catégorie : filtrer sur une catégorie n'en
    retient aucun, et il n'y a donc aucune paire à compléter."""
    source, destination = _deux_comptes(db_session)
    _virement(db_session, source, destination)
    from .conftest import get_categorie_id

    operations = crud.get_operations(
        db_session,
        categorie_id=get_categorie_id(db_session, "Alimentaire"),
        paires_virement=True,
    )

    assert operations == []


# ---------- Ce que le drapeau ne change pas ----------


def test_les_operations_ordinaires_restent_filtrees(db_session):
    """La jambe ramenée est une EXCEPTION réservée aux virements : une dépense
    hors filtre ne doit pas revenir avec."""
    source, destination = _deux_comptes(db_session)
    _virement(db_session, source, destination)
    from .conftest import get_categorie_id, get_type_id

    crud.create_operation(
        db_session,
        schemas.OperationCreate(
            date=date(2026, 9, 15),
            compte_id=destination.id,
            monnaie_id=get_monnaie_id(db_session),
            type_id=get_type_id(db_session, "classique"),
            categorie_id=get_categorie_id(db_session, "Alimentaire"),
            nature="Souvenir",
            montant=30.0,
            statut=Statut.reel,
        ),
    )

    operations = crud.get_operations(
        db_session, compte_id=source.id, paires_virement=True
    )

    assert "Souvenir" not in [op.nature for op in operations]


def test_l_ordre_reste_celui_des_dates(db_session):
    """La jambe ramenée se range à sa date, elle ne s'empile pas à la fin."""
    source, destination = _deux_comptes(db_session)
    _virement(db_session, source, destination, jour=5)
    _virement(db_session, source, destination, jour=20)

    operations = crud.get_operations(
        db_session, compte_id=source.id, paires_virement=True
    )

    dates = [op.date for op in operations]
    assert dates == sorted(dates, reverse=True)
    assert len(operations) == 4


def test_aucun_doublon_quand_les_deux_jambes_passent_le_filtre(db_session):
    """Sans filtre de compte, les deux jambes sont déjà là : les compléter ne
    doit pas les compter deux fois."""
    source, destination = _deux_comptes(db_session)
    _virement(db_session, source, destination)

    operations = crud.get_operations(db_session, paires_virement=True)

    assert len([op for op in operations if op.virement_id is not None]) == 2
    assert len({op.id for op in operations}) == len(operations)
