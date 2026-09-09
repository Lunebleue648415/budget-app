import sys
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import extensions as extensions_noyau
from . import models
from .constants import (
    LIBELLES_SENS_ENTREE,
    LIBELLES_SENS_SORTIE,
    LIBELLES_STATUT_DEFAUT,
    Statut,
)
from .database import get_db
from .routers import (
    categories,
    comptes,
    dashboard,
    extensions,
    import_bancaire,
    monnaies,
    operations,
    parametres_base,
    types_comptes,
    types_operation,
    virements,
)

app = FastAPI(title="Budget App")

app.include_router(monnaies.router)
app.include_router(comptes.router)
app.include_router(categories.router)
app.include_router(types_comptes.router)
app.include_router(types_operation.router)
app.include_router(operations.router)
app.include_router(virements.router)
app.include_router(dashboard.router)
app.include_router(import_bancaire.router)
app.include_router(extensions.router)
# Le panneau « Base de données » : DU NOYAU depuis que l'emplacement par défaut
# est reconnu comme dangereux (il vit dans le dossier que la mise à jour
# remplace). Choisir où ranger ses données n'est plus un outil de mise au point
# mais la seule chose qui les protège — cf. routers/parametres_base.py.
app.include_router(parametres_base.router)


def _monter_extensions() -> list[str]:
    """Monte les routeurs de toutes les extensions PRÉSENTES, actives ou non.

    Actives ou non : démonter un routeur FastAPI à chaud n'est pas prévu par le
    framework, chaque routeur porte donc lui-même une dépendance qui refuse
    l'appel quand son extension est éteinte (cf. extensions.exiger_extension).
    C'est ce qui permet d'activer et de désactiver sans jamais redémarrer.

    Une extension qui casse à l'import est PASSÉE, pas propagée : son erreur
    est collectée et rendue par /extensions/erreurs. Laisser une extension
    défaillante empêcher le démarrage rendrait tout le budget inaccessible à
    cause d'une fonctionnalité annexe.

    AVANT le montage statique du frontend plus bas : celui-ci capte `/` et
    tout ce qui suit, un routeur ajouté après lui ne serait jamais atteint.
    """
    # Le dossier d'accueil d'abord : livré vide, il doit exister pour que
    # l'utilisateur sache où déposer ce qu'il télécharge.
    extensions_noyau.preparer_dossiers()
    # Puis le rattrapage des installations d'avant l'opt-in : une extension qui
    # tournait déjà ne doit pas s'éteindre à la faveur d'une mise à jour, sous
    # prétexte que personne n'avait jamais eu à cocher sa case (cf.
    # extensions.rattraper_etat_avant_opt_in). Sans effet dès le second appel.
    extensions_noyau.rattraper_etat_avant_opt_in()
    problemes = []
    for extension_id, extension in extensions_noyau.decouvrir().items():
        routeur, erreur = extensions_noyau.charger_routeur(extension)
        if erreur is not None:
            problemes.append(f"{extension_id} : {erreur}")
            continue
        if routeur is not None:
            app.include_router(routeur)
    return problemes


# Collectées dans le noyau plutôt que gardées ici : c'est le routeur des
# extensions qui les expose, et il ne peut pas importer main (qui l'importe).
extensions_noyau.ERREURS_CHARGEMENT[:] = _monter_extensions()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/meta")
def get_meta():
    return {
        "statuts": [s.value for s in Statut],
        # Vocabulaire de la colonne « Sens » appliqué tant qu'un preset n'en
        # déclare pas le sien : affiché en exemple dans la configuration
        # avancée, pour que l'utilisateur voie ce qui est déjà compris avant de
        # décider s'il a besoin d'y toucher.
        "libelles_sens_defaut": {
            "sortie": sorted(LIBELLES_SENS_SORTIE),
            "entree": sorted(LIBELLES_SENS_ENTREE),
        },
        # Idem pour la colonne « État », par état.
        "libelles_statut_defaut": {
            statut.value: sorted(libelles)
            for statut, libelles in LIBELLES_STATUT_DEFAUT.items()
        },
    }


@app.get("/meta/periodes")
def get_periodes(inclure_amortissements: bool = True, db: Session = Depends(get_db)):
    """Couples (année, mois) à proposer dans les onglets, plus le mois courant
    même sans opération.

    DEUX QUESTIONS DIFFÉRENTES, D'OÙ LE PARAMÈTRE :

    - « Quels mois PÈSENT quelque chose ? » (`True`, le défaut) — ce que
      demandent le dashboard et les budgets. Une opération amortie ne compte pas
      dans le mois où l'argent est sorti mais dans chacun des mois de son
      étalement (cf. services.soldes.part_amortie) : ces mois-là ont un onglet
      même quand rien d'autre n'y est enregistré, sans quoi une dépense étalée
      sur l'année prochaine alimenterait des histogrammes qu'aucun onglet ne
      permettrait d'atteindre.

    - « Quels mois CONTIENNENT une opération ? » (`False`) — ce que demande la
      page Opérations, qui liste des opérations à leur date. Un mois qui ne
      reçoit qu'une part d'amortissement n'a aucune ligne à y montrer : son
      onglet ouvrait un tableau vide, et il y en avait autant que de mois
      d'étalement.

    Le mois d'origine d'une opération amortie est proposé dans les deux cas :
    l'argent en est bien sorti ce jour-là, et c'est là qu'elle se modifie.
    """
    lignes = db.query(
        models.Operation.date,
        models.Operation.amortissement_debut,
        models.Operation.amortissement_fin,
    ).all()
    periodes = set()
    for date_operation, debut, fin in lignes:
        periodes.add((date_operation.year, date_operation.month))
        if not inclure_amortissements or debut is None or fin is None:
            continue
        # Bornes incluses, normalisées au 1er du mois (cf. schemas.OperationBase) :
        # une simple boucle sur les index de mois couvre le passage d'année.
        for index in range(debut.year * 12 + debut.month, fin.year * 12 + fin.month + 1):
            periodes.add(((index - 1) // 12, (index - 1) % 12 + 1))
    # Le mois courant reste toujours proposé, y compris vide : c'est celui sur
    # lequel l'app s'ouvre (cf. periodeParDefaut côté frontend), et celui où
    # l'on saisit une opération qu'on vient de faire.
    aujourdhui = date.today()
    periodes.add((aujourdhui.year, aujourdhui.month))
    return [{"annee": annee, "mois": mois} for annee, mois in sorted(periodes, reverse=True)]


class NoCacheStaticFiles(StaticFiles):
    """Empêche le navigateur de mettre en cache le HTML/JS/CSS du frontend.

    Le frontend change souvent pendant le développement ; sans ces en-têtes,
    un navigateur peut continuer à servir un app.js périmé qui ne correspond
    plus au index.html courant, ce qui casse silencieusement la page.
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response


def _dossier_frontend() -> Path:
    """En application packagée (PyInstaller), le frontend est embarqué dans le
    bundle et extrait sous sys._MEIPASS ; en développement il est simplement à
    côté du backend dans le repo."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "frontend"
    return Path(__file__).resolve().parents[2] / "frontend"


FRONTEND_DIR = _dossier_frontend()
app.mount("/", NoCacheStaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
