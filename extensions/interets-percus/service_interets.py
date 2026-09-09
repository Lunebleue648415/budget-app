"""Les intérêts perçus : lecture, écriture, et le peu de calcul qui reste.

CE QUI A DISPARU AVEC LE TAUX. Ce fichier faisait 250 lignes : il découpait le
temps en périodes sans mouvement, appliquait un coefficient par période, et
reportait le solde de fin d'une période sur la suivante. Tout cela n'existait
que pour DEVINER ce que la banque annonce noir sur blanc. Il ne reste ici que
lire, écrire, et additionner par monnaie et par année.

L'ADDITION EST LE SEUL « CALCUL », et elle se fait PAR MONNAIE. L'app ne connaît
aucun taux de change et n'additionne jamais deux devises : un compte
multi-devises rend donc un total par devise, jamais un total tout court.
"""
from datetime import date as date_type

from sqlalchemy.orm import Session

# Imports ABSOLUS vers le noyau : ce module n'est pas un sous-paquet de `app`,
# il est chargé par chemin de fichier (cf. extensions/README.md).
from app import models
from app.constants import TYPE_COMPTE_EPARGNE


def comptes_epargne(db: Session) -> list[models.Compte]:
    """Les comptes d'épargne, dans l'ordre d'affichage des comptes.

    SEULEMENT L'ÉPARGNE. Un compte courant ne verse pas d'intérêts, et un
    compte-titres se valorise à son cours — pas en encaissant des intérêts (cf.
    l'extension « Placements financiers »). Restreindre ici évite un écran
    encombré de comptes qui n'auront jamais rien à y montrer."""
    return (
        db.query(models.Compte)
        .join(models.TypeCompte)
        .filter(models.TypeCompte.nom == TYPE_COMPTE_EPARGNE)
        .order_by(models.Compte.ordre, models.Compte.id)
        .all()
    )


def interets_du_compte(db: Session, compte_id: int) -> list[models.InteretPercu]:
    """Les versements d'un compte, du plus récent au plus ancien — l'ordre de
    toutes les listes datées de l'application, et celui dans lequel on cherche
    (« combien cette année ? » avant « combien en 2019 ? »). L'id départage deux
    versements du même jour."""
    return (
        db.query(models.InteretPercu)
        .filter(models.InteretPercu.compte_id == compte_id)
        .order_by(models.InteretPercu.date.desc(), models.InteretPercu.id.desc())
        .all()
    )


def totaux_par_monnaie(interets: list[models.InteretPercu]) -> dict[int, float]:
    """Le total versé, par monnaie. Jamais tous monnaies confondues."""
    totaux: dict[int, float] = {}
    for interet in interets:
        totaux[interet.monnaie_id] = totaux.get(interet.monnaie_id, 0.0) + interet.montant
    return totaux


def totaux_par_annee(interets: list[models.InteretPercu]) -> list[tuple[int, dict[int, float]]]:
    """(année, {monnaie_id: total}) de la plus récente à la plus ancienne.

    PAR ANNÉE parce que c'est le rythme auquel une banque verse et annonce ses
    intérêts, et donc la seule comparaison qui veuille dire quelque chose : « ce
    livret m'a rapporté 142 € en 2025 contre 96 € en 2024 ». Un total par mois
    ne dirait rien — il n'y a qu'un ou deux versements dans l'année."""
    par_annee: dict[int, dict[int, float]] = {}
    for interet in interets:
        annee = par_annee.setdefault(interet.date.year, {})
        annee[interet.monnaie_id] = annee.get(interet.monnaie_id, 0.0) + interet.montant
    return sorted(par_annee.items(), key=lambda item: item[0], reverse=True)


def creer_interet(
    db: Session,
    *,
    compte_id: int,
    monnaie_id: int,
    date: date_type,
    montant: float,
    libelle: str = "",
) -> models.InteretPercu:
    interet = models.InteretPercu(
        compte_id=compte_id,
        monnaie_id=monnaie_id,
        date=date,
        montant=montant,
        libelle=libelle or "",
    )
    db.add(interet)
    db.commit()
    db.refresh(interet)
    return interet


def modifier_interet(db: Session, interet: models.InteretPercu, **champs) -> models.InteretPercu:
    """Applique les champs FOURNIS, et eux seuls.

    Même règle que partout ailleurs dans l'app : `None` veut dire « ne change
    pas », jamais « efface ». Un libellé qu'on veut vider se remplace par la
    chaîne vide, qui est bien une valeur fournie."""
    for nom, valeur in champs.items():
        if valeur is not None:
            setattr(interet, nom, valeur)
    db.commit()
    db.refresh(interet)
    return interet


def supprimer_interet(db: Session, interet: models.InteretPercu) -> None:
    db.delete(interet)
    db.commit()
