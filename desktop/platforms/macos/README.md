# Budget App sous macOS

## Rien à installer

WebKit est fourni avec le système : l'application fonctionne telle quelle.

## Deux archives : prends celle de ton processeur

`budget-app-macos-arm64.zip` pour un Mac à **puce Apple** (M1 et suivants),
`budget-app-macos-x64.zip` pour un Mac à **processeur Intel**.

Menu  → *À propos de ce Mac* le dit en toutes lettres. Se tromper donne une
application que macOS refuse d'ouvrir : un programme compilé pour une
architecture ne s'exécute pas sur l'autre, et Rosetta ne traduit que dans un
sens (Intel vers Apple, jamais l'inverse).

## Premier lancement : Réglages Système → « Ouvrir quand même »

L'application n'est pas signée par un certificat Apple Developer, et Gatekeeper
refuse donc le premier lancement (« impossible d'ouvrir, développeur non
identifié »).

**Depuis macOS 15 (Sequoia), le clic droit → Ouvrir ne débloque plus rien** :
Apple a retiré ce contournement pour lutter contre les logiciels qui en
vivaient. Le geste est désormais :

1. double-clique `Budget App.app` — le refus est attendu, il ne veut pas dire
   que l'application est cassée ;
2. **Réglages Système → Confidentialité et sécurité**, descends jusqu'à la
   section *Sécurité* ;
3. clique **« Ouvrir quand même »**, puis confirme.

Une seule fois : macOS retient le choix, les lancements suivants sont normaux.

**Sur macOS 14 (Sonoma) et antérieur**, l'ancien geste marche toujours : clic
droit sur l'app → *Ouvrir*, puis confirme.

Si le message revient malgré tout :

```bash
xattr -dr com.apple.quarantine "Budget App.app"
```

Cette commande retire l'étiquette de quarantaine posée par le navigateur au
téléchargement. À ne faire, évidemment, que sur une application dont tu connais
la provenance.

## Où sont mes données

Dans `Budget App.app/Contents/MacOS/data/`. Le bundle doit donc être posé dans un
dossier où tu peux écrire : `/Applications` convient, une image disque montée en
lecture seule non.

Pour aller voir : clic droit sur l'app → **Afficher le contenu du paquet**.

## Ça ne démarre pas

Une fenêtre d'erreur s'affiche, et le détail est écrit dans
`Contents/MacOS/data/erreur.log`.
