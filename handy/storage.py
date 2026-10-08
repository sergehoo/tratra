"""Storage backends for files that must never be publicly addressable.

KYC documents use a dedicated storage alias instead of the application's
general media store.  ``KycPrivateStorage`` is deliberately a small proxy:
the model field is instantiated while Django imports models, whereas Django's
``override_settings(STORAGES=...)`` and tests may replace storage backends at
runtime.  Looking the alias up for every operation keeps both behaviours
correct.
"""

from django.core.files.storage import FileSystemStorage, Storage, default_storage, storages
from django.core.files.storage.handler import InvalidStorageError
from django.utils.deconstruct import deconstructible
from storages.backends.s3 import S3Storage


class PrivateKycS3Storage(S3Storage):
    """S3/MinIO storage with private objects and expiring signed URLs only."""

    def __init__(self, **settings):
        settings.setdefault("default_acl", None)
        settings.setdefault("querystring_auth", True)
        settings.setdefault("querystring_expire", 300)
        settings.setdefault("file_overwrite", False)
        super().__init__(**settings)


class PrivateKycFileSystemStorage(FileSystemStorage):
    """Local development storage that cannot be exposed through ``MEDIA_URL``.

    Files are served by the authenticated download action, which streams the
    file when the active backend deliberately has no URL.
    """

    def url(self, name):  # pragma: no cover - exercised via the download view
        raise NotImplementedError("KYC files are available through the authenticated download endpoint.")


@deconstructible
class KycPrivateStorage(Storage):
    """Runtime proxy for the ``private_kyc`` storage alias.

    The fallback is intentionally useful only for isolated tests that replace
    ``STORAGES`` without defining the alias.  Normal application settings
    always define it.
    """

    alias = "private_kyc"

    @property
    def backend(self):
        try:
            return storages[self.alias]
        except InvalidStorageError:
            return default_storage

    def _open(self, name, mode="rb"):
        return self.backend.open(name, mode)

    def _save(self, name, content):
        return self.backend.save(name, content)

    def delete(self, name):
        return self.backend.delete(name)

    def exists(self, name):
        return self.backend.exists(name)

    def listdir(self, path):
        return self.backend.listdir(path)

    def size(self, name):
        return self.backend.size(name)

    def url(self, name):
        return self.backend.url(name)

    def path(self, name):
        return self.backend.path(name)

    def get_accessed_time(self, name):
        return self.backend.get_accessed_time(name)

    def get_created_time(self, name):
        return self.backend.get_created_time(name)

    def get_modified_time(self, name):
        return self.backend.get_modified_time(name)

    def get_available_name(self, name, max_length=None):
        return self.backend.get_available_name(name, max_length=max_length)

    def get_valid_name(self, name):
        return self.backend.get_valid_name(name)

    def get_alternative_name(self, file_root, file_ext):
        return self.backend.get_alternative_name(file_root, file_ext)

    def generate_filename(self, filename):
        return self.backend.generate_filename(filename)
