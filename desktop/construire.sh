#!/usr/bin/env sh
# Reconstruit l'application de bureau — LINUX ET macOS.
#
# À lancer depuis n'importe où :
#     sh desktop/construire.sh
#
# UN SEUL SCRIPT POUR DEUX SYSTÈMES, et c'est voulu : Linux et macOS partagent
# le même shell POSIX, les mêmes chemins et le même enchaînement d'étapes. Ce
# qui les distingue vraiment (format d'icône, bundle .app, boîte d'erreur
# native) vit dans desktop/platforms/<systeme>/ et n'a donc pas à être répété
# ici. Windows, lui, garde son propre script — PowerShell n'est pas un shell
# POSIX (cf. desktop/platforms/windows/construire.ps1).
#
# POURQUOI CE SCRIPT PLUTÔT QU'UN APPEL DIRECT À PyInstaller
#
# PyInstaller (--noconfirm) SUPPRIME l'intégralité du dossier de destination
# avant de le reconstruire — y compris le sous-dossier "data", donc la base de
# données qui vit à côté de l'exécutable (cf. backend/app/database.py : en mode
# packagé, la base est volontairement à côté de l'exe pour survivre à une mise
# à jour de l'app). Appeler PyInstaller à la main efface donc les données, sans
# le moindre avertissement.
#
# D'où la construction DANS UN DOSSIER NEUF, à côté, puis le remplacement du
# seul code dans le bundle en place. "data" n'est jamais ni supprimé ni
# déplacé : rien à restaurer, donc rien à perdre.
#
# Le script applique enfin les migrations en attente : un exécutable neuf sur
# une base ancienne échoue au premier écran concerné (« no such column: ... »),
# ce qui ressemble à un bug de l'app alors qu'il ne manque qu'un
# « alembic upgrade ».
set -eu

DOSSIER_SCRIPT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
RACINE=$(dirname -- "$DOSSIER_SCRIPT")
SAUVEGARDES="$DOSSIER_SCRIPT/sauvegardes"
STAGING="$DOSSIER_SCRIPT/dist_nouveau"

# L'environnement virtuel du dépôt s'il existe, l'interpréteur courant sinon :
# en CI, les dépendances sont installées directement dans le Python du runner,
# il n'y a pas de .venv à trouver.
if [ -x "$RACINE/backend/.venv/bin/python" ]; then
    PYTHON="$RACINE/backend/.venv/bin/python"
else
    PYTHON=$(command -v python3 || command -v python)
fi

# macOS produit un bundle « Budget App.app », les autres un simple dossier.
if [ "$(uname -s)" = "Darwin" ]; then
    NOM_BUNDLE="Budget App.app"
else
    NOM_BUNDLE="Budget App"
fi
BUNDLE="$DOSSIER_SCRIPT/dist/$NOM_BUNDLE"
DATA="$BUNDLE/data"

# L'application verrouille ses propres bibliothèques tant qu'elle tourne : la
# remplacer sous ses pieds laisserait un bundle à moitié écrit. Mieux vaut
# refuser tout de suite, avec un message qui dit quoi faire.
if pgrep -f "Budget App" >/dev/null 2>&1; then
    echo "L'application « Budget App » est en cours d'exécution." >&2
    echo "Ferme-la puis relance ce script." >&2
    exit 1
fi

# Copie horodatée des bases, par simple prudence : le déroulé ci-dessous n'y
# touche pas, mais une reconstruction reste le moment où l'on est content d'en
# avoir une.
if [ -d "$DATA" ]; then
    mkdir -p "$SAUVEGARDES"
    HORODATAGE=$(date +%Y%m%d_%H%M%S)
    for fichier in "$DATA"/*.db; do
        [ -e "$fichier" ] || continue
        base=$(basename -- "$fichier" .db)
        cp -- "$fichier" "$SAUVEGARDES/${base}_${HORODATAGE}.db"
        echo "Sauvegarde : $SAUVEGARDES/${base}_${HORODATAGE}.db"
    done
fi

# Construction dans un dossier neuf : PyInstaller y est seul, il peut le
# nettoyer comme il l'entend sans jamais croiser "data".
rm -rf -- "$STAGING"
echo ""
echo "Reconstruction en cours..."
"$PYTHON" -m PyInstaller "$DOSSIER_SCRIPT/budget_app.spec" --noconfirm \
    --distpath "$STAGING" --workpath "$DOSSIER_SCRIPT/build"

NEUF="$STAGING/$NOM_BUNDLE"
if [ ! -d "$NEUF" ]; then
    echo "Construction incomplète ($NEUF absent) : bundle en place conservé." >&2
    exit 1
fi

# Remplacement du seul code. "data" reste où il est, intouché : on le met de
# côté le temps de l'échange, puis on le remet dans le bundle neuf.
echo ""
echo "Installation du nouveau code..."
mkdir -p -- "$DOSSIER_SCRIPT/dist"
if [ -d "$DATA" ]; then
    mv -- "$DATA" "$STAGING/data_conserve"
fi
rm -rf -- "$BUNDLE"
mv -- "$NEUF" "$BUNDLE"
if [ -d "$STAGING/data_conserve" ]; then
    mv -- "$STAGING/data_conserve" "$DATA"
fi
rm -rf -- "$STAGING"

# CE QUI FAIT DE CE BUNDLE UNE VERSION DÉVELOPPEUR.
#
# Les extensions ne sont plus embarquées dans l'exécutable (cf.
# budget_app.spec) : une version publiée arrive avec un dossier `extensions/`
# vide, à charge pour l'utilisateur d'y déposer ce qu'il télécharge.
#
# Une construction LOCALE, elle, sert à essayer ce qu'on est en train
# d'écrire : les extensions du dépôt sont donc recopiées à côté de
# l'exécutable, `extensions-dev/` comprise. C'est la seule différence entre ce
# bundle et celui que produit la CI.
#
# macOS : les extensions vont dans Contents/MacOS, à côté du binaire — c'est
# là que l'application les cherche (cf. extensions._racine_projet, qui part de
# sys.executable), et là que `data/` se crée déjà.
if [ "$(uname -s)" = "Darwin" ]; then
    RACINE_EXEC="$BUNDLE/Contents/MacOS"
else
    RACINE_EXEC="$BUNDLE"
fi

# CE FICHIER FAIT DE CE BUNDLE UN BUILD DE TEST (cf. database.est_build_de_test).
#
# Le chemin de la base est memorise dans le profil de l'utilisateur, lequel est
# partage par TOUTES les copies de l'application sur la machine. Sans ce
# marqueur, un bundle reconstruit pour essayer trois lignes de code s'ouvrirait
# sur la VRAIE base personnelle. Avec lui, il part toujours de sa propre base de
# test et n'ecrit jamais dans le profil.
#
# Le workflow qui produit les Releases ne le pose PAS : une version publiee doit
# retenir le choix de son utilisateur.
cat > "$RACINE_EXEC/BUILD-DE-TEST.txt" <<'MARQUEUR'
Ce dossier est un BUILD DE TEST, construit en local.

Il ouvre toujours la base de test rangee dans son propre dossier « data », et
n'ecrit jamais dans la configuration de l'application. Changer de base depuis
Parametres -> Base de donnees ne vaut que pour la session.

Supprime ce fichier pour que ce bundle se comporte comme une version publiee.
MARQUEUR

# LE MARQUEUR dit « ce dossier vient du dépôt, ce script l'a posé ». Il permet
# de retirer d'abord tout ce que la construction précédente avait installé —
# sans quoi une extension renommée ou supprimée survivrait dans le bundle, en
# double avec la nouvelle, et serait chargée comme si de rien n'était. Une
# extension déposée À LA MAIN (pour essayer une archive publiée) n'a pas ce
# marqueur : elle n'est jamais touchée.
MARQUEUR=".installee-par-construire"

for nom in extensions extensions-dev; do
    if [ -d "$RACINE_EXEC/$nom" ]; then
        for ancien in "$RACINE_EXEC/$nom"/*/; do
            [ -f "$ancien/$MARQUEUR" ] && rm -rf -- "$ancien"
        done
    fi
    [ -d "$RACINE/$nom" ] || continue
    mkdir -p -- "$RACINE_EXEC/$nom"
    for chemin in "$RACINE/$nom"/*/; do
        [ -d "$chemin" ] || continue
        ext=$(basename -- "$chemin")
        rm -rf -- "$RACINE_EXEC/$nom/$ext"
        cp -R -- "$chemin" "$RACINE_EXEC/$nom/$ext"
        # Les caches Python du dépôt référencent les chemins de la machine de
        # développement : ils n'ont rien à faire dans un bundle.
        find "$RACINE_EXEC/$nom/$ext" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
        : > "$RACINE_EXEC/$nom/$ext/$MARQUEUR"
        echo "Extension installée : $nom/$ext"
    done
done

# Mise à niveau du schéma des bases présentes à côté de l'exécutable.
if [ -d "$DATA" ]; then
    for fichier in "$DATA"/*.db; do
        [ -e "$fichier" ] || continue
        (cd "$RACINE/backend" && BUDGET_DB_PATH="$fichier" "$PYTHON" -m alembic upgrade head)
        echo "Migrations appliquées : $(basename -- "$fichier")"
    done
fi

echo ""
echo "Terminé : $BUNDLE"
echo "Une base personnelle rangée AILLEURS que dans ce dossier n'a rien à faire ici :"
echo "l'application la met à jour toute seule quand tu bascules dessus depuis le panneau"
echo "« Base de données ». Ne lance donc PAS « alembic upgrade » à la main dessus."
