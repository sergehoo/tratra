import pytest


@pytest.fixture(autouse=True)
def _private_kyc_in_tmp(settings, tmp_path):
    """Les tests qui déposent une pièce KYC écrivent dans un dossier temporaire : aucun fichier ne reste dans le dépôt."""
    storages = dict(settings.STORAGES)
    config = dict(storages.get("private_kyc", {}))
    if config.get("BACKEND", "").endswith("FileSystemStorage"):
        options = dict(config.get("OPTIONS", {}))
        options["location"] = str(tmp_path / "private_kyc")
        config["OPTIONS"] = options
        storages["private_kyc"] = config
        settings.STORAGES = storages
