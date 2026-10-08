"""Simulations HTTP/NAS et préparation commune, sans aucun cas de test."""
from contextlib import ExitStack
import io
import ntpath
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import requests
from requests.structures import CaseInsensitiveDict

from synchronisation.utils.fichiers import write_pj_volumineuse
from tests.support.constants import FICHIERS, URL_SIGNEE


class ReponseHTTP:
    def __init__(self, statut=200, headers=None, chunks=(), erreur=None):
        self.status_code = statut
        self.headers = CaseInsensitiveDict(headers or {})
        self.chunks = chunks
        self.erreur = erreur
        self.fermee = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.fermee = True

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code} {URL_SIGNEE}", response=self)

    def iter_content(self, chunk_size):
        yield from self.chunks
        if self.erreur:
            raise self.erreur


class NASMemoire:
    """Le fichier définitif n'est publié qu'au rename/replace, après stat."""
    def __init__(self):
        self.fichiers = {}
        self.ouverts = []
        self.supprimes = []
        self.publies = []
        self.erreurs_ecriture = 0
        self.erreurs_rename = 0
        self.tailles_fausses = 0

    def open_file(self, chemin, mode):
        self.ouverts.append(chemin)
        assert chemin.endswith(".part") and mode == "wb"
        nas = self

        class Ecriture(io.BytesIO):
            def write(self, data):
                if nas.erreurs_ecriture:
                    nas.erreurs_ecriture -= 1
                    super().write(data[:2])
                    raise OSError("Coupure SMB simulée")
                return super().write(data)

            def close(self):
                if not self.closed:
                    nas.fichiers[chemin] = self.getvalue()
                super().close()

        return Ecriture()

    def stat(self, chemin):
        taille = len(self.fichiers[chemin])
        if self.tailles_fausses:
            self.tailles_fausses -= 1
            taille -= 1
        return SimpleNamespace(st_size=taille)

    def remove(self, chemin):
        self.supprimes.append(chemin)
        if chemin not in self.fichiers:
            raise FileNotFoundError(chemin)
        del self.fichiers[chemin]

    def replace(self, source, destination):
        if self.erreurs_rename:
            self.erreurs_rename -= 1
            raise OSError("Renommage SMB interrompu")
        assert source.endswith(".part")
        assert ntpath.dirname(source) == ntpath.dirname(destination)
        self.fichiers[destination] = self.fichiers.pop(source)
        self.publies.append(destination)

    def rename(self, source, destination):
        if destination in self.fichiers:
            raise FileExistsError(destination)
        self.replace(source, destination)

class TelechargementPJMixin:
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.tempdir = self.stack.enter_context(tempfile.TemporaryDirectory(prefix="agida-test-pj-"))
        self.temp_paths = []
        mkstemp_original = tempfile.mkstemp

        def mkstemp_local(**kwargs):
            fd, path = mkstemp_original(dir=self.tempdir, **kwargs)
            self.temp_paths.append(path)
            return fd, path

        self.stack.enter_context(patch(f"{FICHIERS}.tempfile.mkstemp", side_effect=mkstemp_local))
        self.stack.enter_context(patch.dict(os.environ, {"NAS_ROOT": r"\\nas\share"}))
        self.nas = NASMemoire()
        for fonction in ("open_file", "stat", "remove", "rename", "replace"):
            self.stack.enter_context(patch(f"{FICHIERS}.smbclient.{fonction}", side_effect=getattr(self.nas, fonction)))
        self.stack.enter_context(patch(f"{FICHIERS}.smbclient.path.exists", side_effect=lambda p: p in self.nas.fichiers))
        self.stack.enter_context(patch(f"{FICHIERS}.ensure_dossier_root"))
        self.sleep = self.stack.enter_context(patch(f"{FICHIERS}.time.sleep"))
        self.http = self.stack.enter_context(patch(f"{FICHIERS}.requests.get"))
        self.logs = [self.stack.enter_context(patch(f"{FICHIERS}.{nom}")) for nom in ("loggerApp", "loggerORM")]

    def lancer(self, ecrase=True):
        resultat = write_pj_volumineuse("Dossier/Annexes", "document.pdf", URL_SIGNEE, ecrase=ecrase)
        self.assertTrue(all(not os.path.exists(path) for path in self.temp_paths))
        return resultat

