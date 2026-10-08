"""Lanceur Django : isolation active dès la découverte des modules de tests."""
from django.test.runner import DiscoverRunner

from tests.support.isolation import isoler_environnement


class IsolatedTestRunner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        self.isolation = isoler_environnement()
        try:
            super().setup_test_environment(**kwargs)
        except Exception:
            self.isolation.close()
            raise

    def teardown_test_environment(self, **kwargs):
        try:
            super().teardown_test_environment(**kwargs)
        finally:
            self.isolation.close()
