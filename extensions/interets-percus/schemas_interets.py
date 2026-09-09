"""Les formes échangées par l'extension « Intérêts perçus ».

DANS L'EXTENSION et non dans app/schemas.py : ce sont les formes de SES routes,
pas du schéma de la base. La table qu'elles écrivent, elle, vit bien dans le
noyau (migration 0052) — c'est la règle : une extension n'emporte jamais son
schéma, mais elle emporte son vocabulaire.
"""
from datetime import date as date_type
from typing import Optional

from pydantic import BaseModel, Field


class InteretCreate(BaseModel):
    """Un versement d'intérêts, tel que le relevé l'annonce."""

    date: date_type
    # STRICTEMENT POSITIF, comme la contrainte en base. Un intérêt perçu est une
    # entrée : zéro se dit en ne saisissant rien, et un négatif serait des frais
    # — lesquels sont des opérations ordinaires, pas le sujet de cet écran.
    montant: float = Field(gt=0)
    # Facultative : à défaut, c'est la monnaie principale du compte. Un compte
    # mono-devise — le cas de presque tous les livrets — n'a donc rien à dire.
    monnaie_id: Optional[int] = None
    libelle: str = ""


class InteretUpdate(BaseModel):
    """Retouche d'un versement. `None` = ne change pas, jamais « efface » —
    même règle que partout ailleurs dans l'app."""

    date: Optional[date_type] = None
    montant: Optional[float] = Field(default=None, gt=0)
    monnaie_id: Optional[int] = None
    libelle: Optional[str] = None


class InteretRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    compte_id: int
    monnaie_id: int
    date: date_type
    montant: float
    libelle: str


class TotalMonnaieRead(BaseModel):
    """Un total DANS UNE monnaie. Jamais deux devises additionnées."""

    monnaie_id: int
    monnaie_nom: str
    monnaie_symbole: str
    montant: float


class AnneeRead(BaseModel):
    """Ce qu'une année a rapporté, par monnaie.

    PAR ANNÉE parce que c'est le rythme auquel une banque verse et annonce ses
    intérêts : c'est la seule comparaison qui veuille dire quelque chose."""

    annee: int
    totaux: list[TotalMonnaieRead]


class CompteInteretsRead(BaseModel):
    """Un compte d'épargne et ce qu'il a rapporté."""

    id: int
    nom: str
    # Les monnaies du compte, pour que l'écran sache s'il doit proposer un choix
    # (compte multi-devises) ou n'en montrer aucun.
    monnaies: list[TotalMonnaieRead]
    interets: list[InteretRead]
    # Tout ce que le compte a rapporté depuis toujours, par monnaie, et le
    # détail année par année.
    totaux: list[TotalMonnaieRead]
    annees: list[AnneeRead]
