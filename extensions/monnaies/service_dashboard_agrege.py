"""Le dashboard, tout entier ramené à UNE monnaie.

CE QUE CE MODULE FAIT, ET CE QU'IL NE REFAIT PAS. Il n'y a aucun calcul de solde
ici : le dashboard du noyau est appelé tel quel, avec ses KPI par monnaie, et
seule la dernière étape — l'addition entre monnaies, que le noyau se refuse à
faire — est ajoutée. C'est ce qui garantit que la vue convertie et les onglets
par monnaie racontent la même chose : ce sont les mêmes chiffres, additionnés
une fois de plus.

LA MÊME FORME EN SORTIE (`schemas.DashboardRead`), avec une seule monnaie et un
seul jeu de KPI. Le frontend rend donc la vue convertie avec les fonctions du
noyau, sans une ligne d'affichage en double.

CE QUI NE SE CONVERTIT PAS : le budget d'une catégorie. Un budget est posé pour
un mois ET une monnaie (cf. models.Categorie) ; convertir la limite en même
temps que la dépense donnerait un repère qui bouge au gré du taux, ce qui n'est
plus une limite. Le trait rouge de l'histogramme est donc la somme des budgets
convertis, et rien n'y est inventé — mais il faut savoir qu'il flotte, et
l'écran le dit.
"""
from app import schemas
from app.routers import dashboard as dashboard_noyau

import service_conversion


def _categorie_agregee(accumulateur: dict, depense, coefficient: float) -> None:
    """Fond une ligne de catégorie dans son homologue déjà rencontrée.

    LA CLÉ EST LE NOM DE LA CATÉGORIE. Le dashboard rend une liste par monnaie,
    et une même catégorie y apparaît une fois par monnaie où elle a servi :
    « Courses » en euros et « Courses » en dollars sont la même catégorie, et
    c'est justement ce que la conversion permet enfin de dire.
    """
    ligne = accumulateur.setdefault(
        depense.categorie,
        {
            "categorie": depense.categorie,
            "total_reel": 0.0,
            "total_previsionnel": 0.0,
            "budget_alloue": 0.0,
            "top_depenses": [],
            "couleur_index": depense.couleur_index,
        },
    )
    ligne["total_reel"] += depense.total_reel * coefficient
    ligne["total_previsionnel"] += depense.total_previsionnel * coefficient
    ligne["budget_alloue"] += depense.budget_alloue * coefficient
    ligne["top_depenses"].extend(
        schemas.DepenseTopRead(
            nature=top.nature,
            montant=top.montant * coefficient,
            nombre=top.nombre,
        )
        for top in depense.top_depenses
    )


def dashboard_agrege(db, annee, mois, vue: str, vers_monnaie_id: int):
    """Le dashboard converti dans `vers_monnaie_id`.

    Rend (payload, monnaies non converties). La seconde valeur n'est pas un
    détail : une monnaie sans taux est ÉCARTÉE du total, et un total amputé sans
    le dire vaudrait moins qu'un refus.
    """
    brut = dashboard_noyau.get_dashboard(annee=annee, mois=mois, vue=vue, db=db)
    coefficients, manquantes = service_conversion.table_de_conversion(db, vers_monnaie_id)

    cible = next((m for m in brut.monnaies if m.id == vers_monnaie_id), None)
    if cible is None:
        # La monnaie visée n'est portée par aucun compte : il n'y a rien à
        # convertir VERS elle, et l'appelant doit le savoir plutôt que de
        # recevoir un dashboard vide qui aurait l'air normal.
        return None, manquantes

    # ---------- Les KPI, additionnés une fois de plus ----------
    agrege = schemas.KpisMonnaieRead(
        monnaie_id=cible.id,
        monnaie_nom=cible.nom,
        monnaie_symbole=cible.symbole,
        solde_total_courant=0.0,
        solde_projete_courant=0.0,
        total_avoirs=0.0,
    )
    categories: dict = {}
    for kpi in brut.kpis:
        coefficient = coefficients.get(kpi.monnaie_id)
        if coefficient is None:
            continue  # monnaie sans taux : écartée, et nommée dans `manquantes`
        agrege.solde_total_courant += kpi.solde_total_courant * coefficient
        agrege.solde_projete_courant += kpi.solde_projete_courant * coefficient
        agrege.total_avoirs += kpi.total_avoirs * coefficient
        agrege.valorisation_placements += kpi.valorisation_placements * coefficient
        agrege.total_entrees += kpi.total_entrees * coefficient
        agrege.total_sorties += kpi.total_sorties * coefficient
        # La variation brute s'additionne comme les autres totaux : c'est une
        # somme de montants, pas une différence recalculée.
        agrege.variation_brute += kpi.variation_brute * coefficient
        for depense in kpi.depenses_par_categorie:
            _categorie_agregee(categories, depense, coefficient)

    # LA VARIATION N'EST PAS RECALCULÉE À PART. Elle vaut entrées − sorties, et
    # c'est cette garantie que le noyau tient en ne les produisant que d'un seul
    # calcul (cf. services/soldes.get_flux_periode) ; la convertir séparément
    # ouvrirait la porte à trois chiffres qui ne s'accordent plus à l'arrondi.
    agrege.variation_previsionnelle = agrege.total_entrees - agrege.total_sorties

    for ligne in categories.values():
        # Les plus grosses dépenses de la catégorie, tous pays confondus, du
        # plus lourd au plus léger — comme le noyau les rend, mais reclassées :
        # deux listes déjà triées mises bout à bout ne le sont plus.
        ligne["top_depenses"].sort(key=lambda top: top.montant, reverse=True)
        ligne["top_depenses"] = ligne["top_depenses"][:3]
    agrege.depenses_par_categorie = [
        schemas.DepenseParCategorie(**ligne)
        for ligne in sorted(
            categories.values(), key=lambda ligne: ligne["total_previsionnel"], reverse=True
        )
    ]

    # ---------- Les comptes, un solde chacun ----------
    comptes = []
    for compte in brut.comptes:
        total_initial = total_reel = total_projete = 0.0
        for solde in compte.soldes:
            coefficient = coefficients.get(solde.monnaie_id)
            if coefficient is None:
                continue
            total_initial += solde.solde_initial * coefficient
            total_reel += solde.solde_reel * coefficient
            total_projete += solde.solde_projete * coefficient
        comptes.append(
            schemas.CompteSoldeRead(
                id=compte.id,
                nom=compte.nom,
                type_nom=compte.type_nom,
                soldes=[
                    schemas.SoldeMonnaieRead(
                        monnaie_id=cible.id,
                        monnaie_nom=cible.nom,
                        monnaie_symbole=cible.symbole,
                        solde_initial=total_initial,
                        solde_reel=total_reel,
                        solde_projete=total_projete,
                    )
                ],
            )
        )

    return (
        schemas.DashboardRead(comptes=comptes, monnaies=[cible], kpis=[agrege]),
        manquantes,
    )
