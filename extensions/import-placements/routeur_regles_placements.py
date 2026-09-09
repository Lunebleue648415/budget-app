"""Les règles qui disent ce qu'une ligne de relevé de compte-titres décrit,
sous `/regles-import-placements`.

CALQUÉES SUR CELLES DU NOYAU, jusqu'aux noms de routes : liste, création,
réordonnancement, modification, suppression — comme
`extensions/regles/routeur_regles.py`. C'est le même geste à apprendre, et le
même écran à lire.

LA VALIDATION EST DÉJÀ FAITE, presque entièrement, par les schémas Pydantic :
champs connus (`CHAMPS_REGLE_PLACEMENT_VALIDES`), valeur non vide, au moins un
groupe, type de placement parmi les trois. Ne reste ici qu'un croisement, celui
du compte en face et celui du type de titre — et leur NEUTRALISATION pour les
types qui ne les admettent pas, comme le routeur bancaire neutralise sa
catégorie. Les deux sont symétriques : le compte en face n'a de sens que sur un
transfert, l'étiquette de titre partout sauf sur un transfert.

CE ROUTEUR APPARTIENT À L'EXTENSION, LA TABLE AU NOYAU (migration 0042) :
éteindre l'extension ferme ces routes et arrête de consulter les règles à
l'import, sans en perdre une seule.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import crud, schemas
from app.constants import TypeOperationPlacement
from app.database import get_db

router = APIRouter(prefix="/regles-import-placements", tags=["import-placements"])


def _get_regle_ou_404(db: Session, regle_id: int):
    regle = crud.get_regle_import_placement(db, regle_id)
    if regle is None:
        raise HTTPException(status_code=404, detail="Règle introuvable")
    return regle


def _compte_retenu(db: Session, payload) -> int | None:
    """Le compte en face que la règle peut poser, ou None.

    NEUTRALISÉ plutôt que refusé pour un achat ou une vente, exactement comme le
    fait la règle bancaire pour sa catégorie : changer de type dans l'éditeur ne
    doit jamais laisser une combinaison incohérente en base. Un mouvement de
    titres ne touche qu'un compte — un second n'y voudrait rien dire.
    """
    if payload.type_placement is not TypeOperationPlacement.transfert:
        return None
    if payload.compte_autre_id is None:
        return None
    if crud.get_compte(db, payload.compte_autre_id) is None:
        raise HTTPException(status_code=404, detail="Compte en face introuvable")
    return payload.compte_autre_id


def _type_titre_retenu(db: Session, payload) -> int | None:
    """L'étiquette de titre que la règle peut poser, ou None.

    NEUTRALISÉE SUR UN TRANSFERT, pour la raison symétrique de celle du compte
    en face : un transfert d'espèces ne désigne aucun titre, il n'y a donc rien
    à typer. Neutralisée et non refusée — changer de type dans l'éditeur ne doit
    jamais laisser une combinaison incohérente en base.
    """
    if payload.type_placement is TypeOperationPlacement.transfert:
        return None
    if not payload.type_titre_id:
        return None
    if crud.get_type_titre(db, payload.type_titre_id) is None:
        raise HTTPException(status_code=404, detail="Type de titre introuvable")
    return payload.type_titre_id


@router.get("", response_model=list[schemas.RegleImportPlacementRead])
def list_regles(db: Session = Depends(get_db)):
    return crud.list_regles_import_placement(db)


@router.post("", response_model=schemas.RegleImportPlacementRead, status_code=201)
def create_regle(payload: schemas.RegleImportPlacementCreate, db: Session = Depends(get_db)):
    return crud.create_regle_import_placement(
        db,
        nom=payload.nom,
        description=payload.description,
        conditions=payload.conditions.model_dump(mode="json"),
        type_placement=payload.type_placement.value,
        compte_autre_id=_compte_retenu(db, payload),
        type_titre_id=_type_titre_retenu(db, payload),
        actif=payload.actif,
    )


# Déclaré avant /{regle_id} : sinon "reordonner" serait capturé comme un id.
@router.put("/reordonner")
def reordonner_regles(payload: schemas.ReordonnerRegles, db: Session = Depends(get_db)):
    crud.reordonner_regles_import_placement(db, payload.ids)
    return {"reordonnees": len(payload.ids)}


@router.get("/{regle_id}", response_model=schemas.RegleImportPlacementRead)
def get_regle(regle_id: int, db: Session = Depends(get_db)):
    return _get_regle_ou_404(db, regle_id)


@router.put("/{regle_id}", response_model=schemas.RegleImportPlacementRead)
def update_regle(
    regle_id: int,
    payload: schemas.RegleImportPlacementUpdate,
    db: Session = Depends(get_db),
):
    regle = _get_regle_ou_404(db, regle_id)
    return crud.update_regle_import_placement(
        db,
        regle,
        nom=payload.nom,
        description=payload.description,
        conditions=payload.conditions.model_dump(mode="json"),
        type_placement=payload.type_placement.value,
        compte_autre_id=_compte_retenu(db, payload),
        type_titre_id=_type_titre_retenu(db, payload),
        actif=payload.actif,
    )


@router.delete("/{regle_id}")
def delete_regle(regle_id: int, db: Session = Depends(get_db)):
    regle = _get_regle_ou_404(db, regle_id)
    crud.delete_regle_import_placement(db, regle)
    return {"supprime": True}
