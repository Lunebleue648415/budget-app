"""Point d'entrée backend de l'extension « Intérêts perçus ».

Cf. app/extensions.py : le noyau ne cherche ici qu'une variable `router`.

CE QUI N'EST PAS ICI : la table. `interet_percu` vit dans le noyau, posée par la
migration 0052 — une extension n'emporte jamais son schéma. L'éteindre ne perd
donc aucun montant saisi : l'écran disparaît, les lignes restent, et tout revient
à la réactivation.

CE QUE L'EXTENSION NE TOUCHE PAS : le reste de l'application. Aucun solde, aucun
KPI, aucune projection du noyau ne lit cette table, et aucun intérêt n'est jamais
écrit en opération — c'est un suivi d'affichage. Une application dont cette
extension est éteinte se comporte exactement comme si elle n'existait pas.
"""
from fastapi import APIRouter, Depends

from app.extensions import exiger_extension

from routeur_interets import router as router_interets

router = APIRouter(dependencies=[Depends(exiger_extension("interets-percus"))])
router.include_router(router_interets)
