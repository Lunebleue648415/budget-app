from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import crud, models, schemas
from ..constants import (
    CIBLE_PAR_TYPE_REGLEMENT,
    TYPES_AVEC_CATEGORIE_LIBRE,
    TYPES_INTERNES,
    TYPES_REGLEMENT,
    TYPES_REMBOURSABLES,
    TYPE_COMPTE_EPARGNE,
    TYPE_COMPTE_PLACEMENT,
    TypeOperation,
)
from ..database import get_db

router = APIRouter(prefix="/operations", tags=["operations"])


def _valider_compte_operations_libres(compte: models.Compte) -> None:
    """Épargne et placements ne se pilotent pas à l'opération : l'argent y
    arrive et en repart par virement interne, et sur un compte-titres il se
    transforme en titres via la page Placements financiers."""
    if compte.type_nom == TYPE_COMPTE_EPARGNE:
        raise HTTPException(
            status_code=400,
            detail=(
                "Les opérations classiques et remboursements ne peuvent pas cibler "
                "un compte d'épargne ; utilise un virement interne."
            ),
        )
    if compte.type_nom == TYPE_COMPTE_PLACEMENT:
        raise HTTPException(
            status_code=400,
            detail=(
                "Un compte de placements financiers n'accepte que des virements "
                "internes et des achats/ventes de titres (page Placements financiers)."
            ),
        )


def _valider_type(db: Session, type_id: int) -> models.TypeOperationDB:
    type_operation = crud.get_type_operation(db, type_id)
    if type_operation is None:
        raise HTTPException(status_code=404, detail="Type d'opération introuvable")
    if TypeOperation(type_operation.code) == TypeOperation.virement:
        raise HTTPException(
            status_code=400,
            detail=(
                "Le type 'Virement interne' est réservé aux virements, "
                "créés via /virements (deux écritures liées)."
            ),
        )
    if TypeOperation(type_operation.code) in TYPES_INTERNES:
        # Une écriture de ce type ne va jamais seule : elle a une contrepartie
        # (le mouvement de titres) qu'elle seule ne sait pas créer.
        raise HTTPException(
            status_code=400,
            detail=(
                f"Le type « {type_operation.nom} » est géré par la page "
                "Placements financiers et ne peut pas être posé ici."
            ),
        )
    return type_operation


def _refuser_si_interne(operation: models.Operation) -> None:
    """L'écriture d'espèces d'un mouvement de titres n'existe que par sa
    contrepartie : son montant est le produit quantité × prix, et la modifier
    ou la supprimer isolément désaccorderait le portefeuille du solde."""
    if TypeOperation(operation.type_code) in TYPES_INTERNES:
        raise HTTPException(
            status_code=409,
            detail=(
                "Cette écriture appartient à un achat/vente de titres : "
                "modifie-la depuis la page Placements financiers."
            ),
        )


def _valider_monnaie_du_compte(compte: models.Compte, monnaie_id: int) -> None:
    """Une opération ne peut être libellée que dans une monnaie portée par son
    compte : c'est ce qui garantit que chaque montant retombe bien dans l'un
    des soldes calculés pour ce compte (cf. services/soldes.py)."""
    if monnaie_id in compte.monnaie_ids:
        return
    monnaies_possibles = ", ".join(sorted(lien.monnaie.nom for lien in compte.monnaies))
    raise HTTPException(
        status_code=400,
        detail=(
            f"Le compte « {compte.nom} » ne porte pas cette monnaie "
            f"(possibles : {monnaies_possibles})."
        ),
    )


def _valider_categorie(db: Session, categorie_id: int) -> models.Categorie:
    categorie = crud.get_categorie(db, categorie_id)
    if categorie is None:
        raise HTTPException(status_code=404, detail="Catégorie introuvable")
    return categorie


def _cible_valide_pour_reglement(depense: models.Operation, code_reglement: str) -> bool:
    """Un règlement ne peut viser qu'un seul type de cible : un remboursement
    reçu solde une dépense remboursable, un remboursement de prêt solde un prêt
    reçu. Le type remplace à lui seul l'ancien triple test
    (remboursable + sens + nom de catégorie)."""
    cible = CIBLE_PAR_TYPE_REGLEMENT.get(TypeOperation(code_reglement))
    return cible is not None and TypeOperation(depense.type_code) == cible


def _valider_operations_remboursees(
    db: Session,
    items: list[schemas.OperationRembourseeInput],
    code_reglement: str,
    montant_reglement: float,
    monnaie_reglement: int,
    operation_remboursement_id: Optional[int] = None,
) -> None:
    # Le montant de l'opération de règlement est une donnée fixe (celui reçu
    # ou payé en banque) : les liens répartissent ce montant sur les cibles,
    # jamais l'inverse. Leur somme ne peut donc pas le dépasser — elle peut en
    # revanche lui être inférieure (remboursement partiellement affecté).
    # Validation commune à la création et à la modification, donc aux deux
    # écrans qui lient des règlements (page Opérations et import bancaire).
    total_liens = sum(item.montant for item in items)
    if total_liens > montant_reglement + 1e-9:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Le total réglé ({total_liens:.2f}) dépasse le montant de "
                f"l'opération de règlement ({montant_reglement:.2f})"
            ),
        )
    for item in items:
        depense = crud.get_operation(db, item.operation_id)
        if depense is None:
            raise HTTPException(
                status_code=404, detail=f"Opération {item.operation_id} introuvable"
            )
        if not _cible_valide_pour_reglement(depense, code_reglement):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"L'opération {item.operation_id} ne peut pas être réglée par "
                    f"une opération de type '{code_reglement}'"
                ),
            )
        # Le montant du lien est comparé au montant dû de la dette : les deux
        # doivent être libellés dans la même monnaie, sinon on rembourserait
        # « 40 » d'une dette de « 40 » sans qu'il s'agisse du même argent.
        if depense.monnaie_id != monnaie_reglement:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"L'opération {item.operation_id} n'est pas dans la même monnaie "
                    "que ce règlement : l'app ne convertit rien, règle-la depuis une "
                    "opération de sa monnaie."
                ),
            )
        # Somme des autres règlements déjà liés à cette opération (hors celui
        # qu'on est en train de définir, dont on remplace le montant).
        autres_liens_total = sum(
            montant
            for remboursement, montant in crud.get_remboursements_lies_detail(
                db, item.operation_id
            )
            if remboursement.id != operation_remboursement_id
        )
        if autres_liens_total + item.montant > depense.montant_du + 1e-9:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Le montant réglé pour l'opération {item.operation_id} "
                    f"dépasse le montant dû ({depense.montant_du:.2f})"
                ),
            )


def _valider_decoupes(db: Session, code: str, montant: float, decoupes) -> None:
    """Refuse en 400 une découpe que la base ne doit pas voir.

    Deux contrôles, et ils ne se font pas au même endroit : la FORME (au moins
    deux parts, pas de doublon de catégorie, somme égale au montant, type
    `classique`) est jugée par `crud.erreur_decoupes`, partagée avec le dernier
    filet des appels internes ; l'EXISTENCE des catégories visées demande la
    base, et ne peut donc se vérifier qu'ici.
    """
    if not decoupes:
        return
    erreur = crud.erreur_decoupes(code, montant, decoupes)
    if erreur:
        raise HTTPException(status_code=400, detail=erreur)
    for part in decoupes:
        _valider_categorie(db, part.categorie_id)


def _valider_amortissement(
    db_operation: models.Operation, updates: schemas.OperationUpdate
) -> None:
    """Vérifie l'amortissement tel qu'il sera APRÈS la modification.

    À la création, schemas.OperationBase suffit : le payload décrit l'opération
    entière. Une modification, elle, n'en décrit qu'un fragment — déplacer la
    seule borne de fin est légitime, et ce fragment ne dit rien à lui seul des
    deux autres champs. D'où la reconstitution de l'état final ici, avant de le
    juger."""
    champs = updates.model_dump(exclude_unset=True)

    def _final(nom):
        return champs[nom] if nom in champs else getattr(db_operation, nom)

    if not _final("amorti"):
        return
    debut = _final("amortissement_debut")
    fin = _final("amortissement_fin")
    if debut is None or fin is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Une opération amortie doit porter un mois de début et un mois "
                "de fin."
            ),
        )
    if fin < debut:
        raise HTTPException(
            status_code=400,
            detail="Le mois de fin d'amortissement ne peut pas précéder le mois de début.",
        )
    if _final("recurrente"):
        raise HTTPException(
            status_code=400,
            detail=(
                "Une opération ne peut pas être à la fois récurrente et amortie : "
                "chaque occurrence porterait le même amortissement, sur les mêmes mois."
            ),
        )


def _build_operation_read(db: Session, operation: models.Operation) -> schemas.OperationRead:
    read = schemas.OperationRead.model_validate(operation)
    if TypeOperation(operation.type_code) in TYPES_REGLEMENT:
        read.operations_remboursees = [
            schemas.OperationLieeRead(id=depense.id, nature=depense.nature, montant_lien=montant)
            for depense, montant in crud.get_operations_remboursees_detail(db, operation.id)
        ]
    if operation.remboursable:
        read.rembourse_par = [
            schemas.OperationLieeRead(id=remb.id, nature=remb.nature, montant_lien=montant)
            for remb, montant in crud.get_remboursements_lies_detail(db, operation.id)
        ]
    return read


@router.get("", response_model=list[schemas.OperationRead])
def list_operations(
    compte_id: Optional[int] = None,
    categorie_id: Optional[int] = None,
    statut: Optional[str] = None,
    date_debut: Optional[date_type] = None,
    date_fin: Optional[date_type] = None,
    # Bornes de MONTANT, chacune facultative : n'en donner qu'une revient à ne
    # borner que d'un côté (« au moins 500 € », « au plus 20 € »).
    montant_min: Optional[float] = None,
    montant_max: Optional[float] = None,
    # UN VIREMENT EST INDIVISIBLE : avec ce drapeau, une jambe retenue par les
    # filtres ramène l'autre, même si celle-ci ne les respecte pas (cf.
    # crud.get_operations). L'écran Opérations le pose, parce qu'il affiche les
    # virements par paire ; les autres lecteurs de cette route ne le posent pas.
    paires_virement: bool = False,
    db: Session = Depends(get_db),
):
    # Topping-up paresseux des occurrences récurrentes avant toute lecture
    # (cf. crud.generer_occurrences_recurrentes) : garantit que la liste
    # reflète toujours l'horizon glissant, sans tâche planifiée dédiée.
    crud.generer_occurrences_recurrentes(db)
    operations = crud.get_operations(
        db,
        compte_id=compte_id,
        categorie_id=categorie_id,
        statut=statut,
        date_debut=date_debut,
        date_fin=date_fin,
        montant_min=montant_min,
        montant_max=montant_max,
        paires_virement=paires_virement,
    )
    return [_build_operation_read(db, op) for op in operations]


@router.delete("")
def delete_all_operations(db: Session = Depends(get_db)):
    """Supprime toutes les opérations — pensé pour vider des données de test,
    pas pour un usage courant (aucun rattrapage possible ensuite)."""
    nb = crud.delete_all_operations(db)
    return {"supprimees": nb}


@router.post("", response_model=schemas.OperationRead, status_code=status.HTTP_201_CREATED)
def create_operation(operation: schemas.OperationCreate, db: Session = Depends(get_db)):
    compte = crud.get_compte(db, operation.compte_id)
    if compte is None:
        raise HTTPException(status_code=404, detail="Compte introuvable")
    _valider_compte_operations_libres(compte)
    if crud.get_monnaie(db, operation.monnaie_id) is None:
        raise HTTPException(status_code=404, detail="Monnaie introuvable")
    _valider_monnaie_du_compte(compte, operation.monnaie_id)

    type_operation = _valider_type(db, operation.type_id)
    code = type_operation.code
    # La catégorie n'est exigée (et validée) que pour les types qui l'admettent :
    # pour les autres, crud.create_operation la neutralise de toute façon.
    if TypeOperation(code) in TYPES_AVEC_CATEGORIE_LIBRE and operation.categorie_id is not None:
        _valider_categorie(db, operation.categorie_id)

    if operation.operations_remboursees and TypeOperation(code) not in TYPES_REGLEMENT:
        raise HTTPException(
            status_code=400,
            detail=(
                "operations_remboursees n'est valide que pour les types "
                f"{sorted(t.value for t in TYPES_REGLEMENT)}"
            ),
        )
    if operation.operations_remboursees:
        _valider_operations_remboursees(
            db, operation.operations_remboursees, code, operation.montant, operation.monnaie_id
        )

    # La borne de `montant_du` dépend du type et ne peut donc pas se vérifier
    # dans schemas.OperationBase, qui ne voit qu'un `type_id`.
    erreur = crud.erreur_montant_du(code, operation.montant, operation.montant_du)
    if erreur:
        raise HTTPException(status_code=400, detail=erreur)

    # Même raison pour la découpe : sa validité dépend du type et du montant.
    _valider_decoupes(db, code, operation.montant, operation.decoupes)

    db_operation = crud.create_operation(db, operation)
    return _build_operation_read(db, db_operation)


@router.get("/{operation_id}", response_model=schemas.OperationRead)
def read_operation(operation_id: int, db: Session = Depends(get_db)):
    db_operation = crud.get_operation(db, operation_id)
    if db_operation is None:
        raise HTTPException(status_code=404, detail="Opération introuvable")
    return _build_operation_read(db, db_operation)


@router.put("/{operation_id}", response_model=schemas.OperationRead)
def update_operation(
    operation_id: int, updates: schemas.OperationUpdate, db: Session = Depends(get_db)
):
    db_operation = crud.get_operation(db, operation_id)
    if db_operation is None:
        raise HTTPException(status_code=404, detail="Opération introuvable")
    _refuser_si_interne(db_operation)

    compte_final = db_operation.compte
    if updates.compte_id is not None:
        compte_final = crud.get_compte(db, updates.compte_id)
        if compte_final is None:
            raise HTTPException(status_code=404, detail="Compte introuvable")
        _valider_compte_operations_libres(compte_final)

    # Le couple (compte, monnaie) doit rester valide après coup : changer l'un
    # sans l'autre suffit à le rompre.
    monnaie_finale = (
        updates.monnaie_id if updates.monnaie_id is not None else db_operation.monnaie_id
    )
    if updates.monnaie_id is not None and crud.get_monnaie(db, updates.monnaie_id) is None:
        raise HTTPException(status_code=404, detail="Monnaie introuvable")
    _valider_monnaie_du_compte(compte_final, monnaie_finale)

    # Les deux écritures d'un virement doivent rester cohérentes : en reclasser
    # une seule laisserait un virement à moitié converti, dont les soldes ne
    # s'équilibrent plus. Même raison que le 409 au DELETE.
    if (
        db_operation.virement_id is not None
        and updates.type_id is not None
        and updates.type_id != db_operation.type_id
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Cette opération fait partie d'un virement : supprimez le virement "
                "et recréez l'opération pour en changer le type."
            ),
        )

    _valider_amortissement(db_operation, updates)

    code_final = db_operation.type_code
    if updates.type_id is not None and updates.type_id != db_operation.type_id:
        code_final = _valider_type(db, updates.type_id).code
    if (
        TypeOperation(code_final) in TYPES_AVEC_CATEGORIE_LIBRE
        and updates.categorie_id is not None
    ):
        _valider_categorie(db, updates.categorie_id)

    montant = updates.montant if updates.montant is not None else db_operation.montant
    # LE `montant_du` QU'AURA L'OPÉRATION APRÈS COUP, pas celui qu'elle porte.
    # Un type non remboursable n'en porte aucun (0.0, un remplissage, pas une
    # valeur) : le reclasser en prêt sans rien préciser d'autre lui fera poser
    # le montant entier (cf. crud.update_operation). Lire le 0.0 du disque
    # reviendrait à refuser ce reclassement au motif qu'un prêt ne se rembourse
    # pas à zéro — alors que personne n'a demandé zéro.
    if updates.montant_du is not None:
        montant_du = updates.montant_du
    elif TypeOperation(db_operation.type_code) in TYPES_REMBOURSABLES:
        montant_du = db_operation.montant_du
    else:
        montant_du = montant
    montant_a_rembourser = (
        updates.montant_a_rembourser
        if updates.montant_a_rembourser is not None
        else db_operation.montant_a_rembourser
    )
    # Sur l'ÉTAT FINAL, et avec le type final : reclasser une dépense
    # remboursable en prêt fait passer `montant_du` d'un plafond à un plancher.
    erreur = crud.erreur_montant_du(code_final, montant, montant_du)
    if erreur:
        raise HTTPException(status_code=400, detail=erreur)

    # LA DÉCOUPE, ELLE AUSSI SUR L'ÉTAT FINAL. Changer le seul montant d'une
    # opération déjà découpée romprait l'égalité « somme des parts = montant » :
    # c'est refusé plutôt que rattrapé, parce qu'il n'existe aucune façon
    # honnête de décider quelle part encaisse la différence. Renvoyer les parts
    # avec le nouveau montant est le chemin, et c'est ce que fait l'écran.
    _valider_decoupes(
        db,
        code_final,
        montant,
        updates.decoupes if updates.decoupes is not None else db_operation.decoupes,
    )
    if montant_a_rembourser > montant_du:
        raise HTTPException(
            status_code=400, detail="montant_a_rembourser ne peut pas dépasser montant_du"
        )

    # Une fois qu'un remboursement a commencé, les montants de la dette sont
    # figés : les liens déjà posés ont été validés contre le montant_du de
    # l'époque (cf. _valider_operations_remboursees), et rien ne les
    # revalide si ce montant change ensuite — une dette de 100 réglée à 100
    # puis ramenée à 20 laisserait un lien qui sur-rembourse de 80.
    # Se délier d'abord (depuis l'opération de remboursement) est le seul
    # chemin sûr, et il recalcule correctement le reste dû.
    liens_actifs = crud.get_remboursements_lies(db, operation_id)
    if liens_actifs:
        message_verrou = (
            "Cette opération a déjà commencé à être remboursée : {champ} n'est plus "
            "modifiable. Déliez-la d'abord depuis l'opération de remboursement."
        )
        # Comparaison à l'existant plutôt que simple présence dans le payload :
        # le frontend renvoie toujours l'objet complet, y compris les champs
        # inchangés — seule une vraie tentative de modification doit échouer.
        if updates.montant is not None and updates.montant != db_operation.montant:
            raise HTTPException(
                status_code=400, detail=message_verrou.format(champ="le montant")
            )
        if updates.montant_du is not None and updates.montant_du != db_operation.montant_du:
            raise HTTPException(
                status_code=400,
                detail=message_verrou.format(champ="le montant à rembourser"),
            )
        if (
            updates.montant_a_rembourser is not None
            and updates.montant_a_rembourser != 0
            and updates.montant_a_rembourser != db_operation.montant_a_rembourser
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Cette opération est marquée comme remboursée via un remboursement lié ; "
                    "déliez-la d'abord (depuis l'opération de remboursement) pour modifier "
                    "ce montant manuellement."
                ),
            )

    if updates.operations_remboursees is not None:
        if TypeOperation(code_final) not in TYPES_REGLEMENT:
            raise HTTPException(
                status_code=400,
                detail=(
                    "operations_remboursees n'est valide que pour les types "
                    f"{sorted(t.value for t in TYPES_REGLEMENT)}"
                ),
            )
        _valider_operations_remboursees(
            db,
            updates.operations_remboursees,
            code_final,
            montant,
            monnaie_finale,
            operation_remboursement_id=operation_id,
        )

    db_operation = crud.update_operation(db, db_operation, updates)
    return _build_operation_read(db, db_operation)


@router.delete("/{operation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_operation(operation_id: int, db: Session = Depends(get_db)):
    db_operation = crud.get_operation(db, operation_id)
    if db_operation is None:
        raise HTTPException(status_code=404, detail="Opération introuvable")
    _refuser_si_interne(db_operation)
    if db_operation.virement_id is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Cette opération fait partie d'un virement interne ; "
                "elle doit être supprimée via l'endpoint de virement."
            ),
        )
    crud.delete_operation(db, db_operation)
