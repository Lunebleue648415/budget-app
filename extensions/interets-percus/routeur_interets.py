"""Les routes des intérêts perçus, sous `/interets-percus`.

QUATRE ROUTES, et c'est tout ce que l'extension a besoin de faire : lire les
comptes d'épargne avec leurs versements, en ajouter un, le retoucher, le
supprimer.

SEULS LES COMPTES D'ÉPARGNE. Un compte courant ne verse pas d'intérêts, et un
compte-titres se valorise à son cours — pas en encaissant des intérêts (cf.
l'extension « Placements financiers »). Le garde est ici, à l'écriture comme à
la lecture.

RIEN N'EST ÉCRIT EN OPÉRATIONS. Ces routes ne créent aucun mouvement : les
soldes, les KPI et le dashboard ignorent complètement cette table. Si l'intérêt
doit bouger le solde, c'est que le relevé le porte — il entrera donc par
l'import, comme n'importe quelle autre ligne. Saisir deux fois la même chose
ferait diverger le solde de l'app de celui de la banque, ce que toute
l'application est construite pour éviter.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

# Imports ABSOLUS vers le noyau : ce module n'est pas un sous-paquet de `app`,
# il est chargé par chemin de fichier (cf. extensions/README.md).
from app import crud, models
from app.constants import TYPE_COMPTE_EPARGNE
from app.database import get_db

import schemas_interets as schemas_ip
import service_interets as service

router = APIRouter(prefix="/interets-percus", tags=["interets-percus"])


def _get_compte_epargne_ou_404(db: Session, compte_id: int) -> models.Compte:
    compte = crud.get_compte(db, compte_id)
    if compte is None or compte.type_compte.nom != TYPE_COMPTE_EPARGNE:
        raise HTTPException(status_code=404, detail="Compte d'épargne introuvable")
    return compte


def _get_interet_ou_404(db: Session, interet_id: int) -> models.InteretPercu:
    interet = db.get(models.InteretPercu, interet_id)
    if interet is None:
        raise HTTPException(status_code=404, detail="Versement d'intérêts introuvable")
    return interet


def _monnaie_lue(db: Session, monnaie_id: int) -> schemas_ip.TotalMonnaieRead:
    monnaie = crud.get_monnaie(db, monnaie_id)
    return schemas_ip.TotalMonnaieRead(
        monnaie_id=monnaie_id,
        monnaie_nom=monnaie.nom if monnaie else f"#{monnaie_id}",
        monnaie_symbole=monnaie.symbole if monnaie else "",
        montant=0.0,
    )


def _totaux_lus(db: Session, totaux: dict[int, float]) -> list[schemas_ip.TotalMonnaieRead]:
    lus = []
    for monnaie_id, montant in totaux.items():
        lu = _monnaie_lue(db, monnaie_id)
        lu.montant = montant
        lus.append(lu)
    return lus


def _lire_compte(db: Session, compte: models.Compte) -> schemas_ip.CompteInteretsRead:
    interets = service.interets_du_compte(db, compte.id)
    return schemas_ip.CompteInteretsRead(
        id=compte.id,
        nom=compte.nom,
        monnaies=[_monnaie_lue(db, lien.monnaie_id) for lien in compte.monnaies],
        interets=[schemas_ip.InteretRead.model_validate(i) for i in interets],
        totaux=_totaux_lus(db, service.totaux_par_monnaie(interets)),
        annees=[
            schemas_ip.AnneeRead(annee=annee, totaux=_totaux_lus(db, totaux))
            for annee, totaux in service.totaux_par_annee(interets)
        ],
    )


def _valider_monnaie(compte: models.Compte, monnaie_id: int | None) -> int:
    """La monnaie du versement doit être UNE DES MONNAIES DU COMPTE.

    Sans ce contrôle, on pourrait ranger des dollars sur un livret en euros : le
    total par devise afficherait alors une ligne que le compte ne peut pas
    porter, et personne ne saurait d'où elle sort. À défaut, la monnaie
    principale — le cas de presque tous les livrets, mono-devises."""
    if monnaie_id is None:
        return compte.monnaie_principale_id
    if monnaie_id not in compte.monnaie_ids:
        raise HTTPException(
            status_code=400,
            detail=f"La monnaie choisie n'est pas une monnaie du compte « {compte.nom} »",
        )
    return monnaie_id


@router.get("/comptes", response_model=list[schemas_ip.CompteInteretsRead])
def list_comptes_epargne(db: Session = Depends(get_db)):
    """Les comptes d'épargne, leurs versements et leurs totaux."""
    return [_lire_compte(db, compte) for compte in service.comptes_epargne(db)]


@router.post("/comptes/{compte_id}/interets", response_model=schemas_ip.CompteInteretsRead)
def ajouter_interet(
    compte_id: int, payload: schemas_ip.InteretCreate, db: Session = Depends(get_db)
):
    """Le compte ENTIER est rendu, pas seulement la ligne créée : les totaux et
    les années changent à chaque saisie, et les redemander aussitôt ferait deux
    requêtes là où l'écran a besoin d'un seul état cohérent."""
    compte = _get_compte_epargne_ou_404(db, compte_id)
    service.creer_interet(
        db,
        compte_id=compte.id,
        monnaie_id=_valider_monnaie(compte, payload.monnaie_id),
        date=payload.date,
        montant=payload.montant,
        libelle=payload.libelle,
    )
    return _lire_compte(db, compte)


@router.put("/interets/{interet_id}", response_model=schemas_ip.CompteInteretsRead)
def modifier_interet(
    interet_id: int, payload: schemas_ip.InteretUpdate, db: Session = Depends(get_db)
):
    interet = _get_interet_ou_404(db, interet_id)
    compte = _get_compte_epargne_ou_404(db, interet.compte_id)
    champs = payload.model_dump(exclude_none=True)
    if "monnaie_id" in champs:
        champs["monnaie_id"] = _valider_monnaie(compte, champs["monnaie_id"])
    service.modifier_interet(db, interet, **champs)
    return _lire_compte(db, compte)


@router.delete("/interets/{interet_id}", response_model=schemas_ip.CompteInteretsRead)
def supprimer_interet(interet_id: int, db: Session = Depends(get_db)):
    interet = _get_interet_ou_404(db, interet_id)
    compte = _get_compte_epargne_ou_404(db, interet.compte_id)
    service.supprimer_interet(db, interet)
    return _lire_compte(db, compte)
