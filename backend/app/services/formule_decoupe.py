"""Les formules qui disent COMBIEN revient à chaque part d'une découpe.

Une règle d'import ne connaît pas le montant des lignes qu'elle rencontrera :
elle ne peut donc pas poser des nombres, seulement une manière d'en tirer.
« Les 50 premiers euros de chaque note de restaurant vont en Repas, le reste en
Sorties » s'écrit ici `min(montant; 50)` puis `reste`.

LA GRAMMAIRE, EN ENTIER :

    expression := terme (('+' | '-') terme)*
    terme      := facteur (('*' | '/') facteur)*
    facteur    := '-'? primaire
    primaire   := nombre | nombre '%' | 'montant' | 'total'
                | ('min' | 'max') '(' expression (';' | ',') expression ')'
                | '(' expression ')'

Plus un mot à part, `reste`, qui ne s'écrit JAMAIS dans une expression : il est
la formule entière d'une part, et vaut ce que les autres n'ont pas pris.

`total` est un synonyme de `montant` — c'est le mot qui vient naturellement
quand on pense « la valeur totale de l'opération », et refuser un synonyme
évident n'apprend rien à personne.

`30%` VAUT 30 % DU MONTANT, pas 0,3. Une part de découpe se rapporte toujours au
montant de l'opération : c'est la seule lecture possible ici, et c'est la façon
dont un pourcentage se dit à voix haute (« la moitié en Courses, 30 % en
Maison »).

PAS DE `eval`, ET C'EST TOUT L'OBJET DE CE FICHIER. Ces chaînes viennent d'un
formulaire ; les passer à l'interpréteur Python n'aurait pas été une facilité
mais une porte ouverte sur la machine. Un parseur à descente récursive de deux
cents lignes coûte moins cher qu'une seule mauvaise surprise.
"""
import re
from typing import Optional

#: Le mot qui prend ce que les autres parts n'ont pas pris. Écrit ici plutôt
#: qu'en dur aux quatre endroits qui le testent (parseur, répartition, schéma,
#: message d'erreur).
MOT_RESTE = "reste"

#: Les noms qui désignent le montant de l'opération.
_VARIABLES = {"montant", "total"}

_JETONS = re.compile(
    r"""
    (?P<nombre>\d+(?:[.,]\d+)?)     # 12, 12.5, 12,5 -- la virgule décimale est
                                    # admise, c'est ainsi qu'on écrit en français
  | (?P<mot>[A-Za-zÀ-ÿ_]+)
  | (?P<pourcent>%)
  | (?P<operateur>[-+*/()])
  | (?P<separateur>[;,])
  | (?P<espace>\s+)
""",
    re.VERBOSE,
)


class FormuleInvalide(ValueError):
    """Une formule que le parseur refuse. Le message est destiné à
    l'utilisateur : il dit ce qui bloque, pas où en est la pile."""


def _decouper_en_jetons(texte: str) -> list[tuple[str, str]]:
    jetons: list[tuple[str, str]] = []
    position = 0
    while position < len(texte):
        correspondance = _JETONS.match(texte, position)
        if correspondance is None:
            raise FormuleInvalide(
                f"caractère inattendu « {texte[position]} » dans la formule"
            )
        position = correspondance.end()
        genre = correspondance.lastgroup
        if genre == "espace":
            continue
        jetons.append((genre, correspondance.group()))
    return jetons


class _Lecteur:
    """Descente récursive sur la liste de jetons. Une instance par formule ;
    elle n'est pas réutilisable, et n'a pas à l'être."""

    def __init__(self, jetons: list[tuple[str, str]], montant: float):
        self.jetons = jetons
        self.position = 0
        self.montant = montant

    # -- outillage --

    def _regarder(self) -> Optional[tuple[str, str]]:
        if self.position >= len(self.jetons):
            return None
        return self.jetons[self.position]

    def _avancer(self) -> tuple[str, str]:
        jeton = self._regarder()
        if jeton is None:
            raise FormuleInvalide("la formule s'arrête au milieu d'un calcul")
        self.position += 1
        return jeton

    def _attendre(self, valeur: str) -> None:
        jeton = self._regarder()
        if jeton is None or jeton[1] != valeur:
            trouve = "la fin de la formule" if jeton is None else f"« {jeton[1]} »"
            raise FormuleInvalide(f"« {valeur} » attendu, {trouve} trouvé")
        self.position += 1

    # -- grammaire --

    def lire(self) -> float:
        valeur = self.expression()
        if self._regarder() is not None:
            raise FormuleInvalide(
                f"« {self._regarder()[1]} » de trop à la fin de la formule"
            )
        return valeur

    def expression(self) -> float:
        valeur = self.terme()
        while (jeton := self._regarder()) and jeton[1] in "+-":
            self._avancer()
            droite = self.terme()
            valeur = valeur + droite if jeton[1] == "+" else valeur - droite
        return valeur

    def terme(self) -> float:
        valeur = self.facteur()
        while (jeton := self._regarder()) and jeton[1] in "*/":
            self._avancer()
            droite = self.facteur()
            if jeton[1] == "*":
                valeur *= droite
            else:
                # Une division par zéro n'est pas une erreur de frappe qu'on
                # peut repérer à l'écriture : elle dépend du montant de la
                # ligne. Elle remonte donc comme n'importe quelle formule
                # refusée, au moment où elle se produit.
                if abs(droite) < 1e-12:
                    raise FormuleInvalide("division par zéro dans la formule")
                valeur /= droite
        return valeur

    def facteur(self) -> float:
        jeton = self._regarder()
        if jeton and jeton[1] == "-":
            self._avancer()
            return -self.facteur()
        if jeton and jeton[1] == "+":
            self._avancer()
            return self.facteur()
        return self.primaire()

    def primaire(self) -> float:
        genre, valeur = self._avancer()

        if genre == "nombre":
            nombre = float(valeur.replace(",", "."))
            suivant = self._regarder()
            if suivant and suivant[0] == "pourcent":
                self._avancer()
                return self.montant * nombre / 100.0
            return nombre

        if genre == "mot":
            mot = valeur.casefold()
            if mot in _VARIABLES:
                return self.montant
            if mot in ("min", "max"):
                return self._fonction(mot)
            if mot == MOT_RESTE:
                raise FormuleInvalide(
                    "« reste » ne se combine à rien : il doit être la formule "
                    "entière d'une part, à lui tout seul"
                )
            raise FormuleInvalide(f"mot inconnu dans la formule : « {valeur} »")

        if valeur == "(":
            interne = self.expression()
            self._attendre(")")
            return interne

        raise FormuleInvalide(f"« {valeur} » n'a rien à faire là")

    def _fonction(self, nom: str) -> float:
        """`min` et `max` prennent DEUX arguments, séparés par « ; » ou « , ».

        Deux et pas N : c'est ce qu'on écrit dans les faits (« au plus 50 », « au
        moins 10 »), et accepter une liste variable aurait rendu le séparateur
        décimal ambigu — `min(10,5; 20)` veut-il dire deux arguments ou trois ?
        """
        self._attendre("(")
        gauche = self.expression()
        jeton = self._regarder()
        if jeton is None or jeton[0] != "separateur":
            raise FormuleInvalide(
                f"« {nom} » attend deux valeurs séparées par « ; » "
                f"(exemple : {nom}(montant; 50))"
            )
        self._avancer()
        droite = self.expression()
        self._attendre(")")
        return min(gauche, droite) if nom == "min" else max(gauche, droite)


def est_reste(formule: str) -> bool:
    """La formule est-elle le mot `reste` à lui tout seul ?"""
    return (formule or "").strip().casefold() == MOT_RESTE


def evaluer_formule(formule: str, montant: float) -> float:
    """Ce que la formule vaut pour une opération de ce montant.

    `reste` n'est PAS évaluable ici : il ne se calcule qu'en connaissant les
    autres parts (cf. repartir). L'appeler dessus est une erreur de programme,
    pas une formule invalide.
    """
    if est_reste(formule):
        raise FormuleInvalide(
            "« reste » ne s'évalue pas seul : il dépend des autres parts"
        )
    texte = (formule or "").strip()
    if not texte:
        raise FormuleInvalide("la formule est vide")
    return _Lecteur(_decouper_en_jetons(texte), montant).lire()


def valider_formule(formule: str) -> None:
    """Refuse à l'ÉCRITURE une formule que l'import ne saurait pas lire.

    Elle est relue sur un montant fictif de 100 : la validité d'une formule ne
    dépend pas du montant (la grammaire, elle, est fixe), et 100 rend en plus
    les pourcentages représentatifs. Une division par zéro qui n'apparaîtrait
    que pour un certain montant passe donc ici et se signalera à l'import —
    c'est le seul moment où elle existe.
    """
    if est_reste(formule):
        return
    evaluer_formule(formule, 100.0)


def repartir(formules: list[str], montant: float) -> list[float]:
    """Les montants des parts, dans l'ordre, pour une opération de ce montant.

    L'INVARIANT EST TENU ICI, ET NULLE PART AILLEURS : la somme des valeurs
    rendues vaut exactement `montant`, aux centimes. Les parts calculées
    prennent ce que leur formule dit, arrondi au centime ; la part `reste`
    prend la différence. Sans elle, l'utilisateur devrait écrire une
    soustraction exacte des précédentes, et le moindre arrondi produirait une
    découpe refusée à l'import — c'est-à-dire une ligne bloquée pour une raison
    qu'il n'aurait aucun moyen de corriger.

    UNE SEULE PART PEUT VALOIR `reste`, et elle n'a pas à être écrite en
    dernier (l'ordre d'affichage est libre) — elle est simplement servie en
    dernier.

    Sans part `reste`, la somme doit tomber juste d'elle-même : sinon la découpe
    est refusée, en disant de combien elle se trompe. Arrondir en silence la
    dernière part reviendrait à modifier une formule que l'utilisateur a écrite
    exprès.
    """
    index_reste = [i for i, f in enumerate(formules) if est_reste(f)]
    if len(index_reste) > 1:
        raise FormuleInvalide(
            "une seule part peut valoir « reste » : les autres doivent dire "
            "combien elles prennent"
        )

    montants: list[Optional[float]] = []
    for formule in formules:
        if est_reste(formule):
            montants.append(None)
            continue
        valeur = round(evaluer_formule(formule, montant), 2)
        if valeur < 0:
            raise FormuleInvalide(
                f"la formule « {formule} » donne un montant négatif ({valeur:.2f})"
            )
        montants.append(valeur)

    deja_pris = round(sum(v for v in montants if v is not None), 2)

    if index_reste:
        restant = round(montant - deja_pris, 2)
        if restant < 0:
            raise FormuleInvalide(
                f"les parts chiffrées prennent {deja_pris:.2f}, soit plus que le "
                f"montant de l'opération ({montant:.2f}) : il ne reste rien pour "
                "la part « reste »"
            )
        montants[index_reste[0]] = restant
    elif abs(deja_pris - round(montant, 2)) > 0.005:
        raise FormuleInvalide(
            f"les parts totalisent {deja_pris:.2f} au lieu de {montant:.2f} : "
            "ajuste une formule, ou donne la valeur « reste » à l'une des parts"
        )

    return [v for v in montants if v is not None]
