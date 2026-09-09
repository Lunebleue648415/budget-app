from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..constants import (
    PROPRIETES_IMPORT_OBLIGATOIRES,
    PROPRIETES_IMPORT_VALIDES,
    PROPRIETES_MONTANT_SCINDE,
    DomaineImport,
    ModeComparaison,
)
from ..database import get_db
from ..services import import_bancaire

router = APIRouter(prefix="/import", tags=["import"])


def _get_preset_ou_404(db: Session, preset_id: int) -> schemas.ImportPresetRead:
    """Le preset, à condition qu'il soit BANCAIRE.

    Un preset d'un autre domaine (« placement », cf. constants.DomaineImport)
    est traité comme inexistant, et pas seulement par principe : ses colonnes
    désignent des propriétés que ce routeur ne sait pas lire (`nom_valeur`,
    `quantite`…). Le service ne planterait pas pour autant — il ne trouverait
    simplement aucune des siennes et importerait des lignes vides. Un résultat
    faux en silence est bien pire qu'un 404."""
    preset = crud.get_import_preset(db, preset_id)
    if preset is None or preset.domaine != DomaineImport.bancaire.value:
        raise HTTPException(status_code=404, detail="Preset d'import introuvable")
    return preset


def _valider_delimiteur(delimiteur: Optional[str]) -> Optional[str]:
    """Un caractère unique, ou None (auto-détection, comportement par défaut).

    Aucune liste fermée : un relevé peut légitimement utiliser un délimiteur
    hors des trois candidats de la détection automatique (« | », l'espace...),
    et c'est justement pour ce cas que ce réglage existe."""
    if delimiteur is None or delimiteur == "":
        return None
    if len(delimiteur) != 1:
        raise HTTPException(
            status_code=400, detail="Le délimiteur doit être un seul caractère"
        )
    return delimiteur


def _valider_separateur_decimal(separateur_decimal: Optional[str]) -> Optional[str]:
    if separateur_decimal is None or separateur_decimal == "":
        return None
    if separateur_decimal not in (",", "."):
        raise HTTPException(
            status_code=400,
            detail="Le séparateur décimal doit être « , » ou « . »",
        )
    return separateur_decimal


def _valider_compte_lie(db: Session, compte_id: Optional[int]) -> None:
    """Un preset lié à un compte inexistant affecterait toutes ses lignes à
    rien : refusé à l'enregistrement plutôt que découvert au premier import."""
    if compte_id is not None and crud.get_compte(db, compte_id) is None:
        raise HTTPException(status_code=404, detail="Compte introuvable")


def nettoyer_vocabulaire(
    listes: dict[str, list[str]], sujet: str
) -> dict[str, list[str]]:
    """Des listes de mots-clés débarrassées de leurs entrées vides et de leurs
    doublons, et vérifiées : un même mot-clé ne peut pas figurer dans deux
    listes du même groupe.

    La comparaison se fait sur la forme normalisée (« Débit » et « DEBIT » sont
    le même mot-clé, cf. services/import_bancaire.normaliser_libelle), mais ce
    sont les libellés tels que saisis qui sont conservés — c'est ce que
    l'utilisateur relira.

    `sujet` nomme le groupe dans le message d'erreur (« un sens », « un état ») :
    sens et état obéissent à la même règle, il n'y a qu'à la dire correctement.
    """
    propres: dict[str, list[str]] = {}
    for cle, libelles in listes.items():
        vus, retenus = set(), []
        for libelle in libelles:
            normalise = import_bancaire.normaliser_libelle(libelle)
            if not normalise or normalise in vus:
                continue
            vus.add(normalise)
            retenus.append(libelle.strip())
        propres[cle] = retenus

    vus_ailleurs: dict[str, str] = {}
    communs = set()
    for cle, libelles in propres.items():
        for libelle in libelles:
            normalise = import_bancaire.normaliser_libelle(libelle)
            if vus_ailleurs.setdefault(normalise, cle) != cle:
                communs.add(normalise)
    if communs:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Un même mot-clé ne peut pas désigner deux {sujet} différents : "
                f"{', '.join(sorted(communs))}"
            ),
        )
    return propres


def _vocabulaires_nettoyes(payload) -> dict[str, list[str]]:
    """Les cinq listes de mots-clés d'un preset (deux pour le sens, trois pour
    l'état), prêtes à être passées à crud.

    Les deux groupes sont vérifiés SÉPARÉMENT : rien n'interdit qu'un même mot
    désigne une sortie et un état exécuté, ce sont deux colonnes différentes."""
    sens = nettoyer_vocabulaire(
        {
            "libelles_sens_sortie": payload.libelles_sens_sortie,
            "libelles_sens_entree": payload.libelles_sens_entree,
        },
        "sens",
    )
    statut = nettoyer_vocabulaire(
        {
            "libelles_statut_execute": payload.libelles_statut_execute,
            "libelles_statut_attente": payload.libelles_statut_attente,
            "libelles_statut_refuse": payload.libelles_statut_refuse,
        },
        "états",
    )
    return {**sens, **statut}


def _valider_lecture_du_montant(proprietes: set[str]) -> None:
    """D'où vient le montant d'une ligne : d'UNE colonne signée, ou de DEUX
    colonnes dont la position tient lieu de signe. Jamais des deux à la fois.

    Le couple débit/crédit remplace `montant`, il ne le complète pas : les lire
    tous les deux ne dirait pas lequel fait foi quand ils se contredisent, et
    n'importe quel arbitrage se tromperait en silence sur la moitié d'un
    relevé. Même raisonnement pour « Sens », qui porte exactement la même
    information — le fichier écrit le sens dans un mot ou dans le choix de la
    colonne, pas dans les deux.

    Et jamais une seule des deux colonnes : les lignes de l'autre côté
    n'auraient plus de montant du tout, ce qui les mettrait toutes en erreur
    sans dire pourquoi."""
    scinde = set(PROPRIETES_MONTANT_SCINDE) & proprietes
    if not scinde:
        if "montant" not in proprietes:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Propriétés obligatoires manquantes : ['montant'] — ou le "
                    "couple « Montant au débit » / « Montant au crédit »."
                ),
            )
        return

    if len(scinde) < len(PROPRIETES_MONTANT_SCINDE):
        manquante = (set(PROPRIETES_MONTANT_SCINDE) - scinde).pop()
        libelle = "Montant au débit" if manquante == "montant_debit" else "Montant au crédit"
        raise HTTPException(
            status_code=400,
            detail=(
                f"Un montant scindé se lit dans DEUX colonnes : ajoute « {libelle} », "
                "ou repasse au « Montant » unique."
            ),
        )

    if "montant" in proprietes:
        raise HTTPException(
            status_code=400,
            detail=(
                "« Montant » et le couple « Montant au débit » / « Montant au "
                "crédit » décrivent la même chose : choisis l'un ou l'autre."
            ),
        )

    if "sens" in proprietes:
        raise HTTPException(
            status_code=400,
            detail=(
                "« Sens » ne sert à rien avec un montant scindé : c'est la colonne "
                "remplie qui dit déjà si l'argent entre ou sort."
            ),
        )


def valider_colonnes(
    colonnes: list[schemas.ColonneImportConfig],
    proprietes_valides: set[str],
    proprietes_obligatoires: set[str],
) -> set[str]:
    """Ce qu'une liste de colonnes doit respecter QUEL QUE SOIT le domaine :
    au moins une colonne, une propriété par colonne, une colonne par propriété,
    et des propriétés qui existent. Rend l'ensemble des propriétés lues, dont
    l'appelant tire ensuite ses propres vérifications.

    Les deux ensembles sont des paramètres et non des constantes du module :
    c'est tout ce qui distingue un preset bancaire d'un preset de placements de
    ce point de vue, et c'est ce qui permet à l'extension de réutiliser ces
    quatre contrôles au lieu de les récrire."""
    if not colonnes:
        raise HTTPException(status_code=400, detail="Au moins une colonne est requise")

    proprietes = [c.propriete for c in colonnes]
    if len(proprietes) != len(set(proprietes)):
        raise HTTPException(
            status_code=400, detail="Chaque propriété ne peut être assignée qu'à une seule colonne"
        )

    indices = [c.index for c in colonnes]
    if len(indices) != len(set(indices)):
        raise HTTPException(status_code=400, detail="Chaque colonne ne peut être utilisée qu'une fois")

    invalides = set(proprietes) - proprietes_valides
    if invalides:
        raise HTTPException(status_code=400, detail=f"Propriétés invalides : {sorted(invalides)}")

    manquantes = proprietes_obligatoires - set(proprietes)
    if manquantes:
        raise HTTPException(
            status_code=400,
            detail=f"Propriétés obligatoires manquantes : {sorted(manquantes)}",
        )
    return set(proprietes)


def valider_comparaison(
    colonnes_comparaison: list[int], mode_comparaison: ModeComparaison
) -> None:
    """La comparaison de doublons se configure de la même façon dans les deux
    domaines : le détecteur qu'elle pilote est le même code (cf.
    services/import_bancaire.detecter_doublon)."""
    if any(idx < 1 for idx in colonnes_comparaison):
        raise HTTPException(
            status_code=400,
            detail="Les colonnes de la comparaison doivent être numérotées à partir de 1",
        )

    # En mode « seules ces colonnes », une liste vide ne comparerait RIEN :
    # chaque ligne du fichier deviendrait le doublon de la première ligne en
    # stock. Refusé ici plutôt que corrigé en silence — l'utilisateur a
    # visiblement commencé à décrire quelque chose qu'il n'a pas fini.
    if mode_comparaison is ModeComparaison.selection and not colonnes_comparaison:
        raise HTTPException(
            status_code=400,
            detail=(
                "Choisis au moins une colonne à comparer, ou repasse en "
                "« comparer toutes les colonnes sauf »."
            ),
        )


def _valider_configuration(
    colonnes: list[schemas.ColonneImportConfig],
    colonnes_comparaison: list[int],
    mode_comparaison: ModeComparaison,
) -> None:
    """La configuration d'un preset BANCAIRE : les contrôles communs, plus ce
    qui n'a de sens que pour un relevé bancaire (d'où vient le montant)."""
    proprietes = valider_colonnes(
        colonnes, PROPRIETES_IMPORT_VALIDES, PROPRIETES_IMPORT_OBLIGATOIRES
    )
    _valider_lecture_du_montant(proprietes)
    valider_comparaison(colonnes_comparaison, mode_comparaison)


# ---------- Presets ----------


@router.get("/presets", response_model=list[schemas.ImportPresetRead])
def list_presets(db: Session = Depends(get_db)):
    # `dernier_import` n'est pas une colonne : il se lit dans l'historique et
    # sert au frontend à présélectionner le preset réellement utilisé.
    presets = crud.list_import_presets(db, DomaineImport.bancaire.value)
    for preset in presets:
        preset.dernier_import = crud.get_date_dernier_import(db, preset.id)
    return presets


@router.post("/presets", response_model=schemas.ImportPresetRead, status_code=201)
def create_preset(payload: schemas.ImportPresetCreate, db: Session = Depends(get_db)):
    _valider_compte_lie(db, payload.compte_id)
    _valider_configuration(
        payload.colonnes, payload.colonnes_comparaison, payload.mode_comparaison
    )
    return crud.create_import_preset(
        db,
        payload.nom,
        [c.model_dump() for c in payload.colonnes],
        payload.colonnes_comparaison,
        ignorer_premiere_ligne=payload.ignorer_premiere_ligne,
        compte_id=payload.compte_id,
        mode_comparaison=payload.mode_comparaison.value,
        **_vocabulaires_nettoyes(payload),
    )


@router.get("/presets/{preset_id}", response_model=schemas.ImportPresetRead)
def get_preset(preset_id: int, db: Session = Depends(get_db)):
    return _get_preset_ou_404(db, preset_id)


@router.put("/presets/{preset_id}", response_model=schemas.ImportPresetRead)
def update_preset(preset_id: int, payload: schemas.ImportPresetUpdate, db: Session = Depends(get_db)):
    preset = _get_preset_ou_404(db, preset_id)
    _valider_compte_lie(db, payload.compte_id)
    _valider_configuration(
        payload.colonnes, payload.colonnes_comparaison, payload.mode_comparaison
    )
    return crud.update_import_preset(
        db,
        preset,
        nom=payload.nom,
        colonnes=[c.model_dump() for c in payload.colonnes],
        colonnes_comparaison=payload.colonnes_comparaison,
        mode_comparaison=payload.mode_comparaison.value,
        ignorer_premiere_ligne=payload.ignorer_premiere_ligne,
        compte_id=payload.compte_id,
        **_vocabulaires_nettoyes(payload),
    )


@router.delete("/presets/{preset_id}")
def delete_preset(preset_id: int, db: Session = Depends(get_db)):
    preset = _get_preset_ou_404(db, preset_id)
    if len(crud.list_import_presets(db, DomaineImport.bancaire.value)) <= 1:
        raise HTTPException(
            status_code=400, detail="Impossible de supprimer le dernier preset restant"
        )
    crud.delete_import_preset(db, preset)
    return {"supprime": True}


# ---------- Import (scopé à un preset) ----------


@router.post("/presets/{preset_id}/previsualiser", response_model=schemas.ImportPreview)
async def previsualiser(
    preset_id: int,
    fichier: UploadFile = File(...),
    compte_id_defaut: Optional[int] = Form(None),
    delimiteur: Optional[str] = Form(None),
    separateur_decimal: Optional[str] = Form(None),
    colonnes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """`colonnes` : les colonnes que l'ÉCRAN affiche, en JSON, quand elles ne
    sont pas encore celles du preset — on vient de déplacer un en-tête ou de
    corriger un numéro, et on veut voir ce que ça donne avant d'enregistrer.
    Absent, le preset décide, comme avant. Rien n'est écrit dans les deux cas :
    c'est `PUT /presets/{id}` qui enregistre, et lui seul."""
    _get_preset_ou_404(db, preset_id)
    delimiteur = _valider_delimiteur(delimiteur)
    separateur_decimal = _valider_separateur_decimal(separateur_decimal)
    contenu = await fichier.read()
    colonnes_lues = _valider_colonnes_essai(colonnes)
    try:
        return import_bancaire.previsualiser(
            db,
            preset_id,
            contenu,
            compte_id_defaut=compte_id_defaut,
            delimiteur=delimiteur,
            separateur_decimal=separateur_decimal,
            colonnes=colonnes_lues,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Fichier illisible : {exc}")


def _valider_colonnes_essai(colonnes: Optional[str]):
    """Les colonnes d'un essai de lecture, ou None si la requête n'en donne pas.

    VALIDÉES PAR LE MÊME SCHÉMA QUE CELLES DU PRESET : un essai qui lirait deux
    fois la même propriété, ou une propriété inconnue, produirait un aperçu que
    l'enregistrement refuserait ensuite — on aurait montré un import impossible.
    """
    if colonnes is None:
        return None
    try:
        modele = schemas.ColonnesImportEssai.model_validate_json(colonnes)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"colonnes invalides : {exc}")
    # LES MÊMES CONTRÔLES QUE POUR UN PRESET, à ceci près qu'on n'exige PAS les
    # propriétés obligatoires : un essai passe par des états incomplets — on
    # vient de sortir « Montant » d'une colonne pour le poser ailleurs — et
    # refuser de lire le fichier à ce moment-là priverait justement du retour
    # qu'on est en train de chercher. Ce qui est vraiment interdit, ce sont les
    # configurations qui n'ont pas de sens : deux fois la même propriété, deux
    # propriétés sur la même colonne, une propriété qui n'existe pas.
    valider_colonnes(modele.colonnes, PROPRIETES_IMPORT_VALIDES, set())
    return [c.model_dump() for c in modele.colonnes]


@router.post("/presets/{preset_id}/confirmer", response_model=schemas.ImportResultat)
async def confirmer(
    preset_id: int,
    fichier: UploadFile = File(...),
    mappings: str = Form("{}"),
    compte_id_defaut: Optional[int] = Form(None),
    delimiteur: Optional[str] = Form(None),
    separateur_decimal: Optional[str] = Form(None),
    colonnes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """`colonnes` : LES MÊMES que celles de l'aperçu qu'on confirme. L'écran les
    envoie systématiquement, et c'est ce qui garantit qu'on importe ce qu'on
    vient de relire — y compris quand l'arrangement n'est pas encore enregistré
    dans le preset. Rien n'est écrit sur le preset ici non plus."""
    _get_preset_ou_404(db, preset_id)
    delimiteur = _valider_delimiteur(delimiteur)
    separateur_decimal = _valider_separateur_decimal(separateur_decimal)
    contenu = await fichier.read()
    colonnes_lues = _valider_colonnes_essai(colonnes)
    try:
        overrides = schemas.ImportMappingOverrides.model_validate_json(mappings)
    except Exception:
        raise HTTPException(status_code=400, detail="mappings invalide (JSON attendu)")
    try:
        return import_bancaire.confirmer(
            db,
            preset_id,
            contenu,
            overrides,
            nom_fichier=fichier.filename or "",
            compte_id_defaut=compte_id_defaut,
            delimiteur=delimiteur,
            separateur_decimal=separateur_decimal,
            colonnes=colonnes_lues,
        )
    except import_bancaire.ImportBloque as exc:
        # Le fichier est parfaitement lisible : c'est la configuration du preset
        # qui rend l'import impossible. Son message est déjà rédigé pour
        # l'utilisateur et dit quoi corriger — le noyer dans « Fichier
        # illisible » l'enverrait chercher au mauvais endroit.
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Fichier illisible : {exc}")


@router.post("/presets/{preset_id}/lignes-brutes", status_code=201)
async def enregistrer_ligne_brute(
    preset_id: int,
    fichier: UploadFile = File(...),
    ligne: int = Form(...),
    operation_id: int = Form(...),
    delimiteur: Optional[str] = Form(None),
    import_historique_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    """Déclare qu'une ligne du fichier a créé une opération, pour que le même
    relevé la reconnaisse comme doublon la prochaine fois.

    N'existe que pour les règlements liés, seules opérations d'un import à ne
    pas naître de `confirmer` (cf. services.import_bancaire.
    enregistrer_ligne_brute). Le reste du fichier est ignoré : une seule ligne
    entre au stock, celle qui est nommée."""
    _get_preset_ou_404(db, preset_id)
    delimiteur = _valider_delimiteur(delimiteur)
    if crud.get_operation(db, operation_id) is None:
        raise HTTPException(status_code=404, detail="Opération introuvable")
    contenu = await fichier.read()
    try:
        trouvee = import_bancaire.enregistrer_ligne_brute(
            db, preset_id, contenu, ligne, operation_id, delimiteur, import_historique_id
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Fichier illisible : {exc}")
    if not trouvee:
        raise HTTPException(
            status_code=404, detail=f"Ligne {ligne} absente du fichier"
        )
    return {"ligne": ligne, "operation_id": operation_id}


@router.post("/virements-doublons", response_model=schemas.VirementsDoublonsRead)
def virements_doublons(
    payload: schemas.VirementsDoublonsInput, db: Session = Depends(get_db)
):
    """Veille comparative sur les virements internes de l'aperçu en cours.

    Sans preset : deux relevés de deux banques décrivent le même virement avec
    des colonnes qui n'ont rien de commun, et c'est justement pour ça que la
    détection de doublons ordinaire (qui compare des lignes de fichier au sein
    d'un même preset) ne le voit pas. Ici on compare la TRANSACTION — deux
    comptes, un montant, une date voisine.

    Appelé à chaque changement de l'aperçu plutôt qu'à la confirmation : la
    question se pose pendant qu'on compose l'import. Purement consultatif — rien
    n'est bloqué ni écarté.
    """
    return schemas.VirementsDoublonsRead(
        resultats=import_bancaire.detecter_doublons_virements(db, payload.candidats)
    )


def _regrouper_par_cible(mappings, cle_cible):
    """Fond les entrées identiques de plusieurs presets en une seule, en
    retenant les presets concernés : (nom_banque, cible) -> [preset_id].

    Les comptes et les devises sont affichés en une liste commune, sans dire à
    quel preset chacun appartient — répéter « EUR -> Euro » une fois par preset
    n'apprendrait rien. Les entrées qui DIVERGENT (même libellé, cible
    différente) restent distinctes : là, la différence est l'information."""
    groupes: dict[tuple, list[int]] = {}
    premier: dict[tuple, object] = {}
    for m in mappings:
        cle = (m.nom_banque, cle_cible(m))
        groupes.setdefault(cle, []).append(m.preset_id)
        premier.setdefault(cle, m)
    return [(premier[cle], preset_ids) for cle, preset_ids in groupes.items()]


@router.get("/mappings", response_model=schemas.ImportMappingsRead)
def get_mappings(db: Session = Depends(get_db)):
    """Toutes les correspondances mémorisées, tous presets confondus.

    Ce que lit la page Règles : elle n'a pas de sélecteur de preset (il vit sur
    la page Import), et n'en montrer qu'un revenait à cacher le reste sans dire
    lequel. L'écriture, elle, reste scopée au preset — d'où les preset_id
    rapportés ici. Déclaré AVANT /presets/{preset_id}/… : les chemins ne se
    recouvrent pas, mais garde les deux familles d'URL distinctes."""
    categories = [
        schemas.MappingCategorieGlobalRead(
            nom_banque=m.nom_banque,
            categorie_id=m.categorie_id,
            categorie_nom=m.categorie.nom,
            preset_id=m.preset_id,
            compte_nom=compte_nom,
        )
        for m, compte_nom in crud.list_mappings_categorie_tous_presets(db)
    ]
    comptes = [
        schemas.MappingCompteGlobalRead(
            nom_banque=m.nom_banque,
            compte_id=m.compte_id,
            compte_nom=m.compte.nom,
            preset_ids=preset_ids,
        )
        for m, preset_ids in _regrouper_par_cible(
            crud.list_mappings_compte_tous_presets(db), lambda m: m.compte_id
        )
    ]
    monnaies = [
        schemas.MappingMonnaieGlobalRead(
            nom_banque=m.nom_banque,
            monnaie_id=m.monnaie_id,
            monnaie_nom=m.monnaie.nom,
            preset_ids=preset_ids,
        )
        for m, preset_ids in _regrouper_par_cible(
            crud.list_mappings_monnaie_tous_presets(db), lambda m: m.monnaie_id
        )
    ]
    return schemas.ImportMappingsRead(
        categories=categories, comptes=comptes, monnaies=monnaies
    )


@router.put("/presets/{preset_id}/mappings/categorie", response_model=schemas.MappingCategorieRead)
def set_mapping_categorie(
    preset_id: int, payload: schemas.MappingCategorieUpsert, db: Session = Depends(get_db)
):
    _get_preset_ou_404(db, preset_id)
    # Une correspondance ne vise qu'une catégorie de dépense : un libellé qui
    # désigne en réalité un type (« Mouvements internes » -> Virement interne)
    # relève d'une règle de catégorisation, ces types ne portant aucune
    # catégorie (cf. migration 0022).
    categorie = crud.get_categorie(db, payload.categorie_id)
    if categorie is None:
        raise HTTPException(status_code=404, detail="Catégorie introuvable")

    crud.set_mapping_categorie(db, preset_id, payload.nom_banque, payload.categorie_id)
    return schemas.MappingCategorieRead(
        nom_banque=payload.nom_banque,
        categorie_id=payload.categorie_id,
        categorie_nom=categorie.nom,
    )


@router.delete("/presets/{preset_id}/mappings/categorie")
def delete_mapping_categorie(preset_id: int, nom_banque: str, db: Session = Depends(get_db)):
    _get_preset_ou_404(db, preset_id)
    if not crud.delete_mapping_categorie(db, preset_id, nom_banque):
        raise HTTPException(status_code=404, detail="Mapping introuvable")
    return {"supprime": True}


@router.put("/presets/{preset_id}/mappings/compte", response_model=schemas.MappingCompteRead)
def set_mapping_compte(
    preset_id: int, payload: schemas.MappingCompteUpsert, db: Session = Depends(get_db)
):
    _get_preset_ou_404(db, preset_id)
    compte = crud.get_compte(db, payload.compte_id)
    if compte is None:
        raise HTTPException(status_code=404, detail="Compte introuvable")
    crud.set_mapping_compte(db, preset_id, payload.nom_banque, payload.compte_id)
    return schemas.MappingCompteRead(
        nom_banque=payload.nom_banque, compte_id=payload.compte_id, compte_nom=compte.nom
    )


@router.delete("/presets/{preset_id}/mappings/compte")
def delete_mapping_compte(preset_id: int, nom_banque: str, db: Session = Depends(get_db)):
    _get_preset_ou_404(db, preset_id)
    if not crud.delete_mapping_compte(db, preset_id, nom_banque):
        raise HTTPException(status_code=404, detail="Mapping introuvable")
    return {"supprime": True}


@router.put("/presets/{preset_id}/mappings/monnaie", response_model=schemas.MappingMonnaieRead)
def set_mapping_monnaie(
    preset_id: int, payload: schemas.MappingMonnaieUpsert, db: Session = Depends(get_db)
):
    """Mémorise à quelle monnaie de l'app renvoie un libellé de devise du
    fichier (« EUR » -> Euro). Sans cette correspondance, la colonne n'est
    jamais rattachée : rien n'est déduit d'un nom ou d'un symbole identiques
    (cf. services/import_bancaire._resoudre_monnaie)."""
    _get_preset_ou_404(db, preset_id)
    monnaie = crud.get_monnaie(db, payload.monnaie_id)
    if monnaie is None:
        raise HTTPException(status_code=404, detail="Monnaie introuvable")
    crud.set_mapping_monnaie(db, preset_id, payload.nom_banque, payload.monnaie_id)
    return schemas.MappingMonnaieRead(
        nom_banque=payload.nom_banque, monnaie_id=payload.monnaie_id, monnaie_nom=monnaie.nom
    )


@router.delete("/presets/{preset_id}/mappings/monnaie")
def delete_mapping_monnaie(preset_id: int, nom_banque: str, db: Session = Depends(get_db)):
    _get_preset_ou_404(db, preset_id)
    if not crud.delete_mapping_monnaie(db, preset_id, nom_banque):
        raise HTTPException(status_code=404, detail="Mapping introuvable")
    return {"supprime": True}


@router.get("/presets/{preset_id}/historique", response_model=list[schemas.ImportHistoriqueRead])
def get_historique(preset_id: int, db: Session = Depends(get_db)):
    _get_preset_ou_404(db, preset_id)
    entrees = crud.get_import_historique(db, preset_id)
    # Ce qu'annuler chaque import supprimerait AUJOURD'HUI, qui n'est pas ce
    # qu'il a créé le jour même (cf. schemas.ImportHistoriqueRead).
    compteurs = crud.compter_operations_annulables(db, preset_id)

    def _lecture(entree) -> schemas.ImportHistoriqueRead:
        compteur = compteurs.get(entree.id, {"annulables": 0, "sans_lien": 0})
        annulables = compteur["annulables"]
        raison = None
        if annulables == 0:
            # Des lignes de stock existent mais aucune ne désigne d'opération :
            # c'est un import d'avant la migration 0016, définitivement hors de
            # portée — à distinguer de celui dont on a tout supprimé à la main.
            raison = "anterieur" if compteur["sans_lien"] else "deja_supprime"
        return schemas.ImportHistoriqueRead(
            **{
                champ: getattr(entree, champ)
                for champ in (
                    "id",
                    "date_import",
                    "nom_fichier",
                    "operations_creees",
                    "lignes_ignorees",
                    "doublons_detectes",
                )
            },
            operations_annulables=annulables,
            raison_non_annulable=raison,
        )

    return [_lecture(entree) for entree in entrees]


@router.delete(
    "/presets/{preset_id}/historique/{historique_id}",
    response_model=schemas.ImportAnnulationResultat,
)
def annuler_import(preset_id: int, historique_id: int, db: Session = Depends(get_db)):
    """Défait un import : ses opérations, et sa trace dans l'historique.

    Scopé au preset comme le reste de la page : un id d'historique appartenant
    à un autre preset est un 404, et non un import silencieusement annulé
    depuis l'écran d'une autre banque."""
    _get_preset_ou_404(db, preset_id)
    entree = crud.get_import_historique_entree(db, historique_id)
    if entree is None or entree.preset_id != preset_id:
        raise HTTPException(status_code=404, detail="Import introuvable")
    return import_bancaire.annuler_import(db, historique_id)
