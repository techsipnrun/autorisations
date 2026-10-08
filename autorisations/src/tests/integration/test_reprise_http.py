"""Vrai serveur HTTP local ; NAS simulé et aucun service externe."""
from unittest.mock import patch

import requests
from django.test import SimpleTestCase

from synchronisation.utils.fichiers import write_pj_volumineuse

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from tests.support.fichiers import TelechargementPJMixin


class RepriseHTTPTests(TelechargementPJMixin, SimpleTestCase):
    def test_reprise_sur_un_vrai_flux_requests_interrompu(self):
        contenu = b"X" * (3 * 256 * 1024 + 123)
        ranges = []

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                offset = int(self.headers["Range"][6:-1]) if self.headers.get("Range") else 0
                ranges.append(offset)
                self.send_response(206 if offset else 200)
                self.send_header("Content-Length", str(len(contenu) - offset))
                self.send_header("ETag", '"test"')
                self.send_header("Connection", "close")
                if offset:
                    self.send_header("Content-Range", f"bytes {offset}-{len(contenu) - 1}/{len(contenu)}")
                self.end_headers()
                self.wfile.write(contenu[offset:] if offset else contenu[:300000])
                self.wfile.flush()
                self.close_connection = True

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            # requests.api.get n'est pas le symbole requests.get patché dans setUp.
            self.http.side_effect = requests.api.get
            chemin = write_pj_volumineuse("Dossier/Annexes", "document.pdf",
                                          f"http://127.0.0.1:{server.server_port}/?signature=SECRET", ecrase=True)
            self.assertEqual(self.nas.fichiers[chemin], contenu)
            self.assertEqual(ranges, [0, 256 * 1024])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
