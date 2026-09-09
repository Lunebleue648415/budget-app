from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..database import get_db
from ..services import placements, soldes

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/note", response_model=schemas.NoteDashboardRead)
def get_note(db: Session = Depends(get_db)):
    """Le bloc-notes libre affiché en bas du dashboard.

    Déclaré AVANT la route racine n'est pas nécessaire ici (les chemins ne se
    recouvrent pas), mais le groupe reste ensemble pour se lire d'un bloc."""
    note = crud.get_note_dashboard(db)
    if note is None:
        return schemas.NoteDashboardRead()
    return schemas.NoteDashboardRead(contenu=note.contenu, modifie_le=note.modifie_le)


@router.put("/note", response_model=schemas.NoteDashboardRead)
def set_note(payload: schemas.NoteDashboardUpdate, db: Session = Depends(get_db)):
    """Enregistrement automatique côté frontend : cet endpoint est appelé à
    chaque pause de frappe, il doit donc rester trivial (une seule ligne
    réécrite, aucun recalcul déclenché)."""
    note = crud.set_note_dashboard(db, payload.contenu)
    return schemas.NoteDashboardRead(contenu=note.contenu, modifie_le=note.modifie_le)


@router.get("/semaines", response_model=schemas.DepensesSemainesRead)
def get_depenses_semaines(
    monnaie_id: int,
    annee: Optional[int] = None,
    mois: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """L'histogramme des dépenses d'un mois, DÉPLIÉ en semaines.

    Déclaré AVANT la route racine n'est pas nécessaire (les chemins ne se
    recouvrent pas), mais la route reste ici, à côté du dashboard qu'elle
    détaille.

    UNE SEULE MONNAIE, et elle est obligatoire : l'app n'additionne jamais deux
    monnaies, et cette vue détaille l'onglet de monnaie qu'on regarde déjà — il
    n'y a pas de raison de calculer les onze autres pour n'en montrer qu'une.

    PAS DE VUE ANNÉE : les semaines découpent un MOIS. Déplier une année en
    cinquante-deux barres ne serait plus un histogramme, et « la moyenne des
    semaines du mois » n'aurait plus de mois.
    """
    aujourdhui = date.today()
    annee = annee if annee is not None else aujourdhui.year
    mois = mois if mois is not None else aujourdhui.month
    if mois < 1 or mois > 12:
        raise HTTPException(status_code=400, detail="mois doit être entre 1 et 12")

    # Même topping-up que le dashboard : cette route se lit sans être passée par
    # lui (rechargement de page sur l'histogramme déplié).
    crud.generer_occurrences_recurrentes(db)
    return soldes.get_depenses_par_semaine(db, annee, mois, monnaie_id)


@router.get("", response_model=schemas.DashboardRead)
def get_dashboard(
    annee: Optional[int] = None,
    mois: Optional[int] = None,
    vue: str = "mois",
    db: Session = Depends(get_db),
):
    # Les histogrammes (dépenses par catégorie + budget alloué) et la variation
    # prévisionnelle sont scopés à une période : un mois précis (vue="mois",
    # par défaut le mois courant) ou l'année entière (vue="annee", mois
    # ignoré). Le solde projeté est borné à la fin de cette même période ; le
    # solde réel, lui, reste cumulatif (il ne compte que du déjà-survenu).
    if vue not in ("mois", "annee"):
        raise HTTPException(status_code=400, detail="vue doit être 'mois' ou 'annee'")

    aujourdhui = date.today()
    annee = annee if annee is not None else aujourdhui.year
    if vue == "annee":
        mois = None
    else:
        mois = mois if mois is not None else aujourdhui.month
        if mois < 1 or mois > 12:
            raise HTTPException(status_code=400, detail="mois doit être entre 1 et 12")

    # Topping-up paresseux des occurrences récurrentes (cf.
    # crud.generer_occurrences_recurrentes) : le dashboard lit directement la
    # table Operation, il doit rester à jour même sans être passé par
    # GET /operations auparavant.
    crud.generer_occurrences_recurrentes(db)

    comptes_soldes = soldes.get_soldes_comptes(db, date_fin=soldes.fin_de_periode(annee, mois))
    comptes_read = [
        schemas.CompteSoldeRead(
            id=item["compte"].id,
            nom=item["compte"].nom,
            type_nom=item["compte"].type_nom,
            soldes=[
                schemas.SoldeMonnaieRead(
                    monnaie_id=monnaie_id,
                    monnaie_nom=solde["monnaie"].nom,
                    monnaie_symbole=solde["monnaie"].symbole,
                    solde_initial=solde["solde_initial"],
                    solde_reel=solde["solde_reel"],
                    solde_projete=solde["solde_projete"],
                )
                for monnaie_id, solde in item["soldes"].items()
            ],
        )
        for item in comptes_soldes
    ]
    totaux = soldes.calculer_totaux_par_monnaie(
        comptes_soldes, valorisation_placements=placements.valorisation_totale(db)
    )

    # Un onglet par monnaie effectivement portée par un compte : les monnaies
    # créées mais jamais utilisées n'encombrent pas le dashboard. L'ordre est
    # celui de la table `monnaie`, pas celui des comptes, pour que les onglets
    # ne se réorganisent pas au gré des renommages de comptes.
    monnaies_utilisees = {
        monnaie_id for item in comptes_soldes for monnaie_id in item["soldes"]
    } | set(totaux)
    monnaies = [m for m in crud.get_monnaies(db) if m.id in monnaies_utilisees]

    kpis = []
    for monnaie in monnaies:
        totaux_monnaie = totaux.get(monnaie.id, {})
        # Un seul appel pour les trois flux : les recalculer séparément
        # ouvrirait la porte à une variation qui ne vaut pas entrées − sorties.
        flux = soldes.get_flux_periode(db, annee, mois, monnaie.id)
        kpis.append(
            schemas.KpisMonnaieRead(
                monnaie_id=monnaie.id,
                monnaie_nom=monnaie.nom,
                monnaie_symbole=monnaie.symbole,
                solde_total_courant=totaux_monnaie.get("solde_total_courant", 0.0),
                solde_projete_courant=totaux_monnaie.get("solde_projete_courant", 0.0),
                total_avoirs=totaux_monnaie.get("total_avoirs", 0.0),
                valorisation_placements=totaux_monnaie.get("valorisation_placements", 0.0),
                total_entrees=flux["entrees"],
                total_sorties=flux["sorties"],
                variation_previsionnelle=flux["variation"],
                variation_brute=soldes.get_variation_brute(
                    db, annee, mois, monnaie.id
                ),
                depenses_par_categorie=[
                    schemas.DepenseParCategorie(**item)
                    for item in soldes.get_depenses_par_categorie(db, annee, mois, monnaie.id)
                ],
            )
        )

    return schemas.DashboardRead(
        comptes=comptes_read,
        monnaies=[schemas.MonnaieRead.model_validate(m) for m in monnaies],
        kpis=kpis,
    )
