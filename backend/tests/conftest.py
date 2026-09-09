import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import crud, models
from app.constants import (
    CATEGORIES_INITIALES,
    MONNAIE_INITIALE_NOM,
    TYPES_COMPTE_INITIAUX,
    TYPES_COMPTE_SYSTEME,
    TypeOperation,
)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "extensions_reelles: laisse l'état d'activation réel décider "
        "(pour les tests du mécanisme d'extensions lui-même)",
    )


@pytest.fixture(autouse=True)
def extensions_allumees(request, monkeypatch):
    """Les tests s'exécutent avec les extensions ALLUMÉES.

    L'état réel se lit dans `data/extensions.json`, à côté de la base de
    développement : le laisser décider ferait dépendre le résultat d'un fichier
    qui n'appartient pas à la suite, et changerait selon la machine.

    Le défaut d'une extension est « éteinte » (cf. app/extensions.est_active) ;
    or la plupart des tests exercent justement ce que les extensions apportent —
    le classement automatique à l'import, par exemple. Les tests qui vérifient
    le comportement SANS l'extension repatchent `est_active` pour eux seuls.
    """
    if "extensions_reelles" in request.keywords:
        return

    from app import extensions

    monkeypatch.setattr(extensions, "est_active", lambda extension_id: True)


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    session = TestingSessionLocal()
    # Reproduit le seed des migrations : les tests s'appuient sur les mêmes
    # données de départ que la vraie base. Les catégories ne contiennent plus
    # que de vraies catégories de dépense depuis 0019 — les quatre anciennes
    # catégories système sont devenues des types.
    for position, nom in enumerate(CATEGORIES_INITIALES):
        # `couleur_index` suit l'ordre au départ, comme le rattrapage de la
        # migration 0035 : ensuite il n'appartient plus qu'à la catégorie.
        session.add(models.Categorie(nom=nom, ordre=position, couleur_index=position))
    for nom in TYPES_COMPTE_INITIAUX:
        session.add(models.TypeCompte(nom=nom, systeme=nom in TYPES_COMPTE_SYSTEME))
    session.commit()
    # Les 7 types d'opération (migrations 0019 et 0020).
    crud.seed_types_operation(session)
    # L'euro (migration 0021) : la monnaie à laquelle sont rattachées toutes
    # les données qui n'en désignent pas explicitement une autre.
    crud.seed_monnaie_initiale(session)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def get_categorie_id(db, nom):
    return db.query(models.Categorie).filter(models.Categorie.nom == nom).one().id


def get_type_compte_id(db, nom):
    return db.query(models.TypeCompte).filter(models.TypeCompte.nom == nom).one().id


def get_monnaie_id(db, nom=MONNAIE_INITIALE_NOM):
    """Id d'une monnaie depuis son nom ; par défaut l'euro, seule monnaie
    présente au démarrage."""
    return db.query(models.Monnaie).filter(models.Monnaie.nom == nom).one().id


def creer_monnaie(db, nom, symbole):
    return crud.create_monnaie(db, nom, symbole)


def creer_compte(db, nom, type_nom="courant", solde_initial=0.0, monnaies=None):
    """Crée un compte et ses monnaies. `monnaies` est une liste de couples
    (monnaie_id, solde_initial) pour les comptes multi-devises ; sans elle, le
    compte est mono-monnaie en euros avec `solde_initial`."""
    if monnaies is None:
        monnaies = [(get_monnaie_id(db), solde_initial)]
    compte = models.Compte(nom=nom, type_id=get_type_compte_id(db, type_nom))
    compte.monnaies = [
        models.CompteMonnaie(monnaie_id=monnaie_id, solde_initial=montant, ordre=position)
        for position, (monnaie_id, montant) in enumerate(monnaies)
    ]
    db.add(compte)
    db.commit()
    db.refresh(compte)
    return compte


def get_type_id(db, code):
    """Id d'un type d'opération depuis son code technique (`classique`,
    `pret`…) — ce que les opérations référencent désormais."""
    if isinstance(code, TypeOperation):
        code = code.value
    return (
        db.query(models.TypeOperationDB).filter(models.TypeOperationDB.code == code).one().id
    )


def charger_module_extension(extension_id: str, nom_fichier: str):
    """Importe un module d'une extension, pour les tests qui l'exercent.

    Les extensions ne sont pas des paquets Python installés : leurs modules se
    chargent par chemin de fichier, comme le fait l'application elle-même
    (cf. app/extensions.py::charger_routeur). Ce raccourci évite à chaque test
    de refaire cette plomberie.

    Cherche dans `extensions/` puis `extensions-dev/` : un test qui vise
    l'extension de développement (« outils-dev ») la trouve donc aussi, sans
    avoir à dire où elle vit.
    """
    import importlib.util
    import sys
    from pathlib import Path

    racine = Path(__file__).resolve().parents[2]
    for base in ("extensions", "extensions-dev"):
        dossier = racine / base / extension_id
        chemin = dossier / nom_fichier
        if not chemin.is_file():
            continue
        # Comme dans l'application : le dossier rejoint le sys.path pour que
        # les fichiers de l'extension puissent s'importer entre eux.
        if str(dossier) not in sys.path:
            sys.path.append(str(dossier))
        spec = importlib.util.spec_from_file_location(
            f"budget_ext_test_{extension_id}_{Path(nom_fichier).stem}", chemin
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    raise ImportError(f"Module {nom_fichier} introuvable dans l'extension {extension_id}")
