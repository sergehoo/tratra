"""Fournisseurs de TEST uniquement (injectés par les tests) : jamais sélectionnables par la configuration, donc jamais utilisés en production."""
from biometrics.providers import BiometricProvider, ProviderError, ProviderResult


class FakeProvider(BiometricProvider):
    name = "fake"

    def __init__(self, result: ProviderResult = None, error: bool = False):
        self._result, self._error, self.calls = result, error, []

    def configured(self) -> bool:
        return True

    def verify(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise ProviderError("Timeout")
        return self._result
