# Reconstruit l'application de bureau WINDOWS à partir du code courant.
#
# À lancer depuis la racine du dépôt :
#     powershell -ExecutionPolicy Bypass -File desktop\platforms\windows\construire.ps1
#
# Équivalents des autres systèmes : desktop/platforms/linux/construire.sh et
# desktop/platforms/macos/construire.sh. Les trois font la même chose et
# appellent la même spec générique (desktop/budget_app.spec) ; seul le langage
# de script et le format du bundle produit diffèrent.
#
# POURQUOI CE SCRIPT PLUTÔT QU'UN APPEL DIRECT À PyInstaller
#
# PyInstaller (--noconfirm) SUPPRIME l'intégralité de "dist\Budget App\" avant
# de la reconstruire — y compris le sous-dossier "data", donc la base de
# données qui vit à côté de l'exécutable (cf. backend/app/database.py : en mode
# packagé, la base est volontairement à côté de l'exe pour survivre à une mise
# à jour de l'app). Appeler PyInstaller à la main efface donc les données, sans
# le moindre avertissement.
#
# Pire : cette suppression échoue à mi-parcours dès qu'un fichier est
# verrouillé — l'app en cours d'exécution, ou la synchronisation OneDrive sur
# le dossier "data". Elle laisse alors un bundle à moitié effacé, qui ne
# démarre plus (« Can't find Python file ... alembic\env.py »).
#
# D'où la construction DANS UN DOSSIER NEUF, à côté, puis le remplacement du
# seul code (_internal + exe) dans le bundle en place. "data" n'est jamais ni
# supprimé ni déplacé : rien à restaurer, donc rien à perdre, et aucun verrou
# à forcer.
#
# Le script applique enfin les migrations en attente : un exécutable neuf sur
# une base ancienne échoue au premier écran concerné (« no such column: ... »),
# ce qui ressemble à un bug de l'app alors qu'il ne manque qu'un
# « alembic upgrade ».

$ErrorActionPreference = "Stop"

# Ce script vit dans desktop\platforms\windows\ : deux remontées pour
# atteindre desktop\, une troisième pour la racine du dépôt.
$DossierScript = Split-Path -Parent $MyInvocation.MyCommand.Path
$Desktop = Split-Path -Parent (Split-Path -Parent $DossierScript)
$Racine = Split-Path -Parent $Desktop
$Python = Join-Path $Racine "backend\.venv\Scripts\python.exe"
$Bundle = Join-Path $Desktop "dist\Budget App"
$Data = Join-Path $Bundle "data"
$Sauvegardes = Join-Path $Desktop "sauvegardes"

# L'exe verrouille ses propres DLL tant qu'il tourne : la suppression du
# dossier échoue alors à mi-chemin, ce qui laisse un bundle à moitié effacé.
# Mieux vaut refuser tout de suite, avec un message qui dit quoi faire.
#
# SEULES LES INSTANCES LANCÉES DEPUIS CE BUNDLE COMPTENT. Un `Get-Process -Name
# "Budget App"` attrapait n'importe quelle copie de l'application ouverte sur la
# machine -- une release téléchargée dans « Downloads », par exemple -- et
# refusait de reconstruire alors qu'elle ne verrouille rien ici. Sur une machine
# où l'on développe l'application ET où on l'utilise pour de vrai, ça revenait à
# devoir fermer son budget pour compiler.
$EnCours = Get-CimInstance Win32_Process -Filter "Name = 'Budget App.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($Bundle, [StringComparison]::OrdinalIgnoreCase) }
if ($EnCours) {
    Write-Host "Une application « Budget App » de CE bundle est en cours d'exécution (PID $($EnCours.ProcessId))." -ForegroundColor Red
    Write-Host "  $($EnCours.ExecutablePath)"
    Write-Host "Ferme-la puis relance ce script : PyInstaller ne peut pas remplacer un bundle verrouillé."
    exit 1
}

# Copie horodatée des bases, par simple prudence : le déroulé ci-dessous n'y
# touche pas, mais une reconstruction reste le moment où l'on est content d'en
# avoir une.
if (Test-Path $Data) {
    New-Item -ItemType Directory -Force -Path $Sauvegardes | Out-Null
    $Horodatage = Get-Date -Format "yyyyMMdd_HHmmss"
    foreach ($fichier in Get-ChildItem -Path $Data -Filter *.db) {
        $cible = Join-Path $Sauvegardes "$($fichier.BaseName)_$Horodatage.db"
        Copy-Item $fichier.FullName $cible
        Write-Host "Sauvegarde : $cible"
    }
}

# Construction dans un dossier neuf : PyInstaller y est seul, il peut le
# nettoyer comme il l'entend sans jamais croiser "data" ni un fichier verrouillé.
$Staging = Join-Path $Desktop "dist_nouveau"
if (Test-Path $Staging) { Remove-Item $Staging -Recurse -Force }

Write-Host "`nReconstruction en cours..." -ForegroundColor Cyan
& $Python -m PyInstaller (Join-Path $Desktop "budget_app.spec") --noconfirm `
    --distpath $Staging --workpath (Join-Path $Desktop "build")
if ($LASTEXITCODE -ne 0) {
    Write-Host "Échec de la reconstruction. Le bundle en place n'a pas été touché." -ForegroundColor Red
    exit 1
}

$Neuf = Join-Path $Staging "Budget App"
if (-not (Test-Path (Join-Path $Neuf "_internal\alembic\env.py"))) {
    Write-Host "Construction incomplète (alembic absent) : bundle en place conservé." -ForegroundColor Red
    exit 1
}

# Remplacement du seul code. "data" reste où il est, intouché.
Write-Host "`nInstallation du nouveau code..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $Bundle | Out-Null
$AncienInternal = Join-Path $Bundle "_internal"
if (Test-Path $AncienInternal) { Remove-Item $AncienInternal -Recurse -Force }
Copy-Item (Join-Path $Neuf "_internal") $Bundle -Recurse -Force
Get-ChildItem -Path $Neuf -File | ForEach-Object { Copy-Item $_.FullName $Bundle -Force }
Remove-Item $Staging -Recurse -Force

# CE FICHIER FAIT DE CE BUNDLE UN BUILD DE TEST (cf. database.est_build_de_test).
#
# Le chemin de la base est mémorisé dans le profil de l'utilisateur, lequel est
# partagé par TOUTES les copies de l'application sur la machine. Sans ce
# marqueur, un bundle reconstruit pour essayer trois lignes de code s'ouvrirait
# sur la VRAIE base personnelle -- et une manipulation de test se ferait sur de
# vraies finances. Avec lui, ce bundle part toujours de sa propre base de test,
# à côté de lui, et n'écrit jamais dans le profil.
#
# Le workflow qui produit les Releases ne le pose PAS : une version publiée doit
# retenir le choix de son utilisateur, c'est ce qui protège ses données des
# mises à jour.
@'
Ce dossier est un BUILD DE TEST, construit en local.

Il ouvre toujours la base de test rangée dans son propre dossier « data », et
n'écrit jamais dans la configuration de l'application (%LOCALAPPDATA%\Budget App).
Changer de base depuis Paramètres -> Base de données ne vaut que pour la session.

Supprime ce fichier pour que ce bundle se comporte comme une version publiée.
'@ | Set-Content -Path (Join-Path $Bundle "BUILD-DE-TEST.txt") -Encoding utf8

# CE QUI FAIT DE CE BUNDLE UNE VERSION DÉVELOPPEUR.
#
# Les extensions ne sont plus embarquées dans l'exécutable (cf.
# budget_app.spec) : une version publiée arrive avec un dossier `extensions/`
# vide, à charge pour l'utilisateur d'y déposer ce qu'il télécharge.
#
# Une construction LOCALE, elle, sert à essayer ce qu'on est en train
# d'écrire : les extensions du dépôt sont donc recopiées à côté de
# l'exécutable, `extensions-dev/` comprise. C'est la seule différence entre ce
# bundle et celui que produit la CI — et c'est ce qui rend les outils de
# développement (« Base de données ») accessibles ici et nulle part ailleurs.
# LE MARQUEUR dit « ce dossier vient du dépôt, ce script l'a posé ». Il permet
# de retirer d'abord tout ce que la construction précédente avait installé —
# sans quoi une extension renommée ou supprimée survivrait dans le bundle, en
# double avec la nouvelle, et serait chargée comme si de rien n'était. Une
# extension déposée À LA MAIN (pour essayer une archive publiée) n'a pas ce
# marqueur : elle n'est jamais touchée.
$Marqueur = ".installee-par-construire"

foreach ($nom in @("extensions", "extensions-dev")) {
    $cible = Join-Path $Bundle $nom
    if (Test-Path $cible) {
        foreach ($ancien in Get-ChildItem -Path $cible -Directory) {
            if (Test-Path (Join-Path $ancien.FullName $Marqueur)) {
                Remove-Item $ancien.FullName -Recurse -Force
            }
        }
    }
    $source = Join-Path $Racine $nom
    if (-not (Test-Path $source)) { continue }
    New-Item -ItemType Directory -Force -Path $cible | Out-Null
    foreach ($ext in Get-ChildItem -Path $source -Directory) {
        $destination = Join-Path $cible $ext.Name
        if (Test-Path $destination) { Remove-Item $destination -Recurse -Force }
        Copy-Item $ext.FullName $destination -Recurse -Force
        # Les caches Python du dépôt n'ont rien à faire dans un bundle : ils
        # référencent les chemins de la machine de développement.
        Get-ChildItem -Path $destination -Filter "__pycache__" -Recurse -Directory -ErrorAction SilentlyContinue |
            ForEach-Object { Remove-Item $_.FullName -Recurse -Force }
        New-Item -ItemType File -Force -Path (Join-Path $destination $Marqueur) | Out-Null
        Write-Host "Extension installée : $nom\$($ext.Name)"
    }
}

# Mise à niveau du schéma des bases présentes à côté de l'exe.
foreach ($base in Get-ChildItem -Path $Data -Filter *.db -ErrorAction SilentlyContinue) {
    $env:BUDGET_DB_PATH = $base.FullName
    Push-Location (Join-Path $Racine "backend")
    & $Python -m alembic upgrade head
    Pop-Location
    Remove-Item Env:\BUDGET_DB_PATH
    Write-Host "Migrations appliquées : $($base.Name)"
}

Write-Host "`nTerminé : $Bundle" -ForegroundColor Green
Write-Host "Une base personnelle rangée AILLEURS que dans ce dossier n'a rien à faire ici :"
Write-Host "l'application la met à jour toute seule quand tu bascules dessus depuis le panneau"
Write-Host "« Base de données » (copie horodatée prise juste avant, à côté du fichier)."
Write-Host "Ne lance donc PAS « alembic upgrade » à la main dessus."
