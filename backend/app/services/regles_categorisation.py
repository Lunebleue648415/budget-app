"""Classement automatique des lignes d'un relevé bancaire.

Le "type" d'une opération (classique / remboursable / remboursement /
virement / prêt / remboursement de prêt) est une colonne depuis la migration
0019 (table `type_operation`). Rien ne le posait automatiquement à l'import —
il fallait reclasser chaque ligne à la main. Une règle fait ce travail à
partir des libellés du relevé.

Structure d'une règle (RegleCategorisation.conditions), calquée sur les
filtres Notion, sur deux niveaux :

    {"operateur": "ET",                     <- combine les groupes
     "groupes": [
        {"operateur": "OU",                 <- combine les conditions du groupe
         "conditions": [
            {"champ": "nature",
             "operateur": "contient",
             "valeur": "PRET"}]}]}

Deux niveaux suffisent à exprimer "(A OU B) ET (C OU D)". Une condition porte
sur un seul champ : viser plusieurs champs se fait en ajoutant autant de
conditions dans un groupe "OU", ce qui rend la combinaison explicite.

Les comparaisons sont insensibles à la casse ET aux accents : les libellés
bancaires sont irrégulièrement accentués et souvent tout en majuscules
("VIR SEPA REMBOURSEMENT" vs "Virement remboursé"), une règle écrite
naturellement doit malgré tout correspondre.
"""
import unicodedata
from dataclasses import dataclass
from typing import NamedTuple, Optional

from ..constants import (
    OPERATEURS_NOMBRE,
    TYPES_AVEC_CATEGORIE_LIBRE,
    ConnecteurRegle,
    OperateurRegle,
    TypeOperation,
)
from .formule_decoupe import FormuleInvalide, repartir


@dataclass
class ResultatRegle:
    """Ce qu'une règle impose à la ligne : son type, et — seulement si ce type
    l'admet — sa catégorie. Le caractère remboursable en découle, il n'est plus
    porté séparément.

    `compte_autre_id` ne concerne que le virement interne : c'est le compte EN
    FACE, que le relevé ne nomme jamais (il ne décrit qu'un côté de la
    transaction). Sans lui, chaque virement reconnu par une règle devait être
    repris à la main dans l'aperçu avant de pouvoir être importé."""

    nom_regle: str
    type_code: str
    categorie_id: Optional[int] = None
    compte_autre_id: Optional[int] = None
    #: La DÉCOUPE que la règle impose, en couples (catégorie, formule) — pas
    #: encore en montants : une règle est écrite une fois pour des lignes dont
    #: elle ne connaît pas le montant, et le montant final d'une opération
    #: importée n'est arrêté qu'après les frais (cf. import_bancaire).
    #: C'est donc l'appelant qui la résout, quand il tient le bon montant
    #: (cf. resoudre_decoupes). None = la règle ne découpe pas.
    decoupes: Optional[list[tuple[int, str]]] = None

    @property
    def classe(self) -> bool:
        """La règle a-t-elle déjà dit dans QUELLE catégorie la ligne tombe ?

        Une catégorie unique et une découpe répondent à la même question et
        s'excluent : sans ce test commun, une règle de complément aurait pu
        poser une catégorie sur une ligne qu'une règle plus haute avait déjà
        découpée, et l'histogramme aurait compté la dépense deux fois."""
        return self.categorie_id is not None or self.decoupes is not None


def _normaliser(texte) -> str:
    """Minuscules sans accents, pour comparer "Remboursé" et "REMBOURSE".

    NFD sépare chaque lettre accentuée en (lettre + diacritique) ; on retire
    ensuite les diacritiques (catégorie Unicode "Mn", mark nonspacing).
    """
    if texte is None:
        return ""
    decompose = unicodedata.normalize("NFD", str(texte))
    sans_accents = "".join(c for c in decompose if unicodedata.category(c) != "Mn")
    return sans_accents.casefold().strip()


def _en_nombre(valeur) -> Optional[float]:
    """Un nombre lisible dans `valeur`, ou None.

    LA VIRGULE DÉCIMALE EST ADMISE, et les espaces (y compris insécables) qui
    séparent les milliers sont retirés : les deux côtés de la comparaison
    peuvent venir d'un formulaire écrit en français (« 1 500,50 ») aussi bien
    que d'un montant déjà converti en float par le lecteur de relevé."""
    if valeur is None:
        return None
    if isinstance(valeur, (int, float)):
        return float(valeur)
    texte = str(valeur).replace(" ", "").replace(" ", "")
    texte = texte.replace(" ", "").replace(",", ".").strip()
    if not texte:
        return None
    try:
        return float(texte)
    except ValueError:
        return None


def _comparer_nombres(valeur_champ, operateur: str, valeur_regle: str) -> bool:
    """Les six opérateurs numériques. Un champ illisible ou absent ne
    correspond à AUCUN d'eux, « différent de » compris : une ligne dont on
    ignore le montant n'est pas une ligne dont le montant diffère de 50, c'est
    une ligne sur laquelle la règle n'a rien à dire."""
    gauche = _en_nombre(valeur_champ)
    droite = _en_nombre(valeur_regle)
    if gauche is None or droite is None:
        return False
    if operateur == OperateurRegle.egal.value:
        # Une tolérance au centime, comme partout où l'app compare des
        # montants : 49.999999 saisi par un tableur EST 50.
        return abs(gauche - droite) < 0.005
    if operateur == OperateurRegle.different.value:
        return abs(gauche - droite) >= 0.005
    if operateur == OperateurRegle.superieur.value:
        return gauche > droite
    if operateur == OperateurRegle.superieur_ou_egal.value:
        return gauche >= droite
    if operateur == OperateurRegle.inferieur.value:
        return gauche < droite
    if operateur == OperateurRegle.inferieur_ou_egal.value:
        return gauche <= droite
    return False


def _comparer(valeur_champ, operateur: str, valeur_regle: str) -> bool:
    # L'OPÉRATEUR CHOISIT LA FAMILLE, pas le champ : c'est lui qui est stocké
    # dans la condition, et le schéma a déjà vérifié à l'écriture qu'il va bien
    # avec son champ. Se fier ici au nom du champ aurait demandé de rejouer
    # cette vérification, et d'échouer autrement en cas de désaccord.
    if operateur in {o.value for o in OPERATEURS_NOMBRE}:
        return _comparer_nombres(valeur_champ, operateur, valeur_regle)
    champ = _normaliser(valeur_champ)
    attendu = _normaliser(valeur_regle)
    if operateur == OperateurRegle.est.value:
        return champ == attendu
    if operateur == OperateurRegle.nest_pas.value:
        return champ != attendu
    if operateur == OperateurRegle.contient.value:
        return attendu in champ
    if operateur == OperateurRegle.ne_contient_pas.value:
        return attendu not in champ
    # Opérateur inconnu (donnée corrompue en base) : ne jamais correspondre,
    # plutôt que de faire échouer tout l'import.
    return False


def _mots_cles(condition: dict) -> list:
    """Les valeurs que la condition compare, dans l'ordre.

    `valeurs` est la forme canonique (plusieurs mots-clés, combinés en ET) ;
    `valeur` est celle d'avant, et une règle enregistrée alors ne porte qu'elle.
    Les deux sont lues ici plutôt que migrées en base : le JSON des conditions
    est libre, et une migration qui le réécrirait devrait comprendre toutes ses
    formes passées pour n'apporter que la commodité de n'en lire qu'une."""
    valeurs = condition.get("valeurs")
    if valeurs:
        return [v for v in valeurs if str(v).strip()]
    return [condition.get("valeur", "")]


def evaluer_condition(condition: dict, brute: dict) -> bool:
    """Une condition porte sur un seul champ, et sur UN OU PLUSIEURS mots-clés.

    LES MOTS-CLÉS SE COMBINENT EN ET, y compris pour les opérateurs négatifs :
    « ne contient pas A ni B » est ce qu'on veut dire en les écrivant tous les
    deux, et c'est ce que le ET donne.

    Tolère l'ancienne forme `champs: [...]` (avant le passage au champ unique) :
    une règle enregistrée avant ce changement reste évaluable, ses champs
    multiples étant combinés en OU comme à l'origine.
    """
    operateur = condition.get("operateur")
    mots = _mots_cles(condition)
    if "champ" in condition:
        valeur_champ = brute.get(condition["champ"])
        return all(_comparer(valeur_champ, operateur, mot) for mot in mots)
    return any(
        all(_comparer(brute.get(champ), operateur, mot) for mot in mots)
        for champ in condition.get("champs") or []
    )


def evaluer_groupe(groupe: dict, brute: dict) -> bool:
    conditions = groupe.get("conditions") or []
    if not conditions:
        return False
    resultats = (evaluer_condition(c, brute) for c in conditions)
    if groupe.get("operateur") == ConnecteurRegle.ou.value:
        return any(resultats)
    return all(resultats)


def evaluer_regle(conditions: dict, brute: dict) -> bool:
    """`conditions` est le JSON complet de RegleCategorisation.conditions."""
    groupes = (conditions or {}).get("groupes") or []
    if not groupes:
        # Une règle sans condition s'appliquerait à tout : refusée côté
        # routeur, ignorée ici par sécurité.
        return False
    resultats = (evaluer_groupe(g, brute) for g in groupes)
    if (conditions or {}).get("operateur") == ConnecteurRegle.ou.value:
        return any(resultats)
    return all(resultats)


def appliquer_regles(regles, brute: dict) -> Optional[ResultatRegle]:
    """Descend les règles actives dans l'ordre de `ordre`, et s'arrête où on
    lui a dit de s'arrêter.

    La première règle qui correspond pose le TYPE, et le type ne change plus :
    c'est lui qui décide de ce que la ligne est, les règles suivantes ne
    peuvent que compléter ce qu'il laisse ouvert (la catégorie, le compte en
    face). Si elle porte `arreter_apres` — le cas par défaut, et le
    comportement historique — l'évaluation s'arrête là.

    Sinon on continue vers le bas, et chaque règle rencontrée ne remplit que
    les cases encore vides. C'est ce qui fait que **la règle la plus haute
    l'emporte toujours** en cas de désaccord : deux règles ne se disputent
    jamais un champ, la première l'a déjà rempli. Sans cette priorité stricte,
    l'ordre — qui est toute la lisibilité du système — ne voudrait plus rien
    dire.

    Une règle qui correspond sans rien apporter de neuf ne s'attribue pas le
    résultat : seules celles qui ont réellement décidé quelque chose sont
    nommées dans `nom_regle`, faute de quoi le badge « via … » de l'aperçu
    citerait des règles sans effet.

    `brute` est le dict produit par import_bancaire.lire_lignes_brutes
    (clés `nature`, `categorie_banque`, `compte_banque`).
    """
    resultat: Optional[ResultatRegle] = None
    noms: list[str] = []

    for regle in sorted(regles, key=lambda r: (r.ordre, r.id)):
        if not regle.actif:
            continue
        if not evaluer_regle(regle.conditions, brute):
            continue

        if resultat is None:
            type_operation = TypeOperation(regle.type_operation.code)
            resultat = ResultatRegle(nom_regle=regle.nom, type_code=type_operation.value)
            noms.append(regle.nom)
            _completer(resultat, regle, type_operation)
        else:
            type_operation = TypeOperation(resultat.type_code)
            if _completer(resultat, regle, type_operation):
                noms.append(regle.nom)

        if regle.arreter_apres:
            break

    if resultat is None:
        return None
    resultat.nom_regle = " + ".join(noms)
    return resultat


def _completer(resultat: ResultatRegle, regle, type_operation: TypeOperation) -> bool:
    """Verse dans `resultat` ce que `regle` apporte et qui manque encore.

    `type_operation` est celui DÉJÀ RETENU, pas celui de `regle` : une règle de
    complément propose une catégorie ou un compte en face, jamais un autre type
    — et ce qu'elle propose n'est retenu que si le type retenu l'admet. Une
    catégorie posée par une règle sur un type à catégorie imposée serait une
    incohérence en base, exactement celle que le routeur refuse à l'écriture.

    Renvoie True si quelque chose a été posé, pour que l'appelant sache si
    cette règle a compté.
    """
    pose = False
    # LA CATÉGORIE ET LA DÉCOUPE OCCUPENT LA MÊME CASE (cf. ResultatRegle.classe).
    # Une règle propose l'une ou l'autre — jamais les deux, le routeur les rend
    # exclusives à l'écriture — et ne la pose que si personne ne l'a fait avant.
    if not resultat.classe and type_operation in TYPES_AVEC_CATEGORIE_LIBRE:
        if regle.decoupes:
            resultat.decoupes = [(part.categorie_id, part.formule) for part in regle.decoupes]
            pose = True
        elif regle.categorie_id is not None:
            resultat.categorie_id = regle.categorie_id
            pose = True
    # Seul un virement a un compte en face : sur tout autre type, ce serait un
    # second compte sur une opération qui n'en touche qu'un.
    if (
        resultat.compte_autre_id is None
        and regle.compte_autre_id is not None
        and type_operation == TypeOperation.virement
    ):
        resultat.compte_autre_id = regle.compte_autre_id
        pose = True
    return pose


def resoudre_decoupes(
    decoupes: Optional[list[tuple[int, str]]], montant: float
) -> tuple[Optional[list[tuple[int, float]]], Optional[str]]:
    """Transforme les formules d'une règle en montants, pour un montant donné.

    Rend `(parts, None)` en cas de succès, `(None, message)` sinon — jamais
    d'exception : l'appelant est l'aperçu d'import, qui doit AFFICHER une ligne
    fautive parmi les autres, pas s'interrompre. Un relevé de trois cents lignes
    dont une seule fait tomber une formule doit rester importable pour les deux
    cent quatre-vingt-dix-neuf autres.

    LA DÉCOUPE EST ABANDONNÉE SI ELLE ÉCHOUE — la ligne garde son type et
    n'aura simplement pas de catégorie, comme si aucune règle ne l'avait
    classée. Le message remonte à l'écran d'aperçu, où la ligne se reprend à la
    main.
    """
    if not decoupes:
        return None, None
    if montant is None:
        return None, "montant inconnu : la découpe ne peut pas être calculée"
    try:
        montants = repartir([formule for _, formule in decoupes], abs(montant))
    except FormuleInvalide as erreur:
        return None, f"découpe impossible ({erreur})"
    return [
        (categorie_id, part)
        for (categorie_id, _), part in zip(decoupes, montants)
        # Une part nulle ne classe rien et ferait échouer la contrainte
        # `montant > 0` de la table : une formule qui rend 0 sur cette
        # ligne-là (« min(montant; 50) » sur une opération à 0) veut dire
        # « rien pour cette catégorie », pas « une part vide ».
        if part > 0
    ], None


# ---------- Règles d'import de placements ----------
#
# LE MÊME MOTEUR, POUR L'AUTRE DOMAINE. Tout ce qui précède — la normalisation,
# les quatre opérateurs, les deux niveaux de groupes — ne parle que de texte et
# ne sait rien des types d'opération : `evaluer_regle` prend un JSON de
# conditions et un dict de valeurs brutes, et c'est tout. Il se réemploie donc
# tel quel sur un relevé de compte-titres, dont les lignes brutes portent
# simplement d'autres clés (`type_brut`, `nom_valeur_brut`, `code_isin_brut`).
#
# Seule l'ACTION diffère, et elle tient en une valeur : ce que la ligne décrit.
# D'où une fonction de dix lignes ici plutôt qu'un second module.


class DecisionPlacement(NamedTuple):
    """Ce qu'une règle de placement impose à une ligne.

    UN TUPLE NOMMÉ plutôt qu'un tuple nu qui s'allonge : il en portait deux
    valeurs, il en porte trois, et rien ne dit qu'il n'en portera pas une
    quatrième. Les appelants lisent des noms, et ajouter un champ ne décale plus
    aucun indice.
    """

    #: "achat" | "vente" | "transfert" (constants.TypeOperationPlacement).
    type_placement: str
    #: Le compte EN FACE, pour un transfert seulement. None ailleurs.
    compte_autre_id: Optional[int]
    #: Le type à poser sur le TITRE que la ligne désigne, quand l'import le crée.
    #: None = la règle ne dit rien du type.
    type_titre_id: Optional[int]


def appliquer_regles_placement(regles, brute: dict) -> Optional[DecisionPlacement]:
    """Ce que la première règle correspondante impose, ou None si aucune ne
    correspond.

    LE COMPTE EN FACE n'accompagne qu'un transfert, et vaut None partout
    ailleurs — le routeur le neutralise déjà à l'écriture, on n'a pas à le
    refaire ici. Il évite à chaque transfert reconnu par la règle d'arriver
    incomplet dans l'aperçu : un relevé de compte-titres ne nomme jamais que son
    propre compte.

    LE TYPE DE TITRE est le troisième champ. Il ne décrit pas la ligne mais la
    VALEUR qu'elle touche (« MSCI World » EST un ETF), et l'import ne le pose
    donc qu'au moment où il crée le titre — jamais sur un titre déjà connu, sans
    quoi un import mal réglé retyperait tout un portefeuille sans le dire.

    PAS DE COMPLÉMENT ni de poursuite après la première correspondance,
    contrairement aux règles bancaires : celles-là décident de plusieurs choses
    et peuvent donc se partager le travail entre plusieurs règles. Ici la règle
    qui décide du type décide aussi du compte — deux règles ne peuvent que se
    contredire, et c'est la plus haute qui a raison.

    `brute` est le dict produit par import_bancaire.lire_lignes_brutes sur un
    preset de domaine « placement ».
    """
    for regle in sorted(regles, key=lambda r: (r.ordre, r.id)):
        if not regle.actif:
            continue
        if evaluer_regle(regle.conditions, brute):
            return DecisionPlacement(
                regle.type_placement,
                regle.compte_autre_id,
                regle.type_titre_id,
            )
    return None
