"""Téléchargement et copie NAS simulés."""
from http.client import IncompleteRead
import tempfile
from unittest.mock import call, patch

import requests
from django.test import SimpleTestCase
from urllib3.exceptions import ProtocolError

from tests.support.constants import FICHIERS, URL_SIGNEE

from tests.support.fichiers import ReponseHTTP, TelechargementPJMixin


class TelechargementPJTests(TelechargementPJMixin, SimpleTestCase):
    def test_reprise_apres_deux_coupures_conserve_les_octets_et_if_range(self):
        interruption = requests.exceptions.ChunkedEncodingError(ProtocolError("interrupted", IncompleteRead(b"", 7)))
        reponses = [
            ReponseHTTP(headers={"Content-Length": "10", "ETag": '"v1"'}, chunks=[b"abc"], erreur=interruption),
            ReponseHTTP(206, {"Content-Range": "bytes 3-9/10", "Content-Length": "7", "ETag": '"v1"'}, [b"def"], interruption),
            ReponseHTTP(206, {"Content-Range": "bytes 6-9/10", "Content-Length": "4", "ETag": '"v1"'}, [b"ghij"]),
        ]
        self.http.side_effect = reponses
        chemin = self.lancer()
        self.assertEqual(self.nas.fichiers[chemin], b"abcdefghij")
        headers = [c.kwargs["headers"] for c in self.http.call_args_list]
        self.assertNotIn("Range", headers[0])
        self.assertEqual(headers[1]["Range"], "bytes=3-")
        self.assertEqual(headers[2]["Range"], "bytes=6-")
        self.assertEqual(headers[1]["If-Range"], '"v1"')
        self.assertEqual(headers[0]["Accept-Encoding"], "identity")
        self.assertTrue(all(r.fermee for r in reponses))
        self.assertEqual(self.sleep.call_args_list, [call(2), call(4)])
        self.assertEqual(len(self.nas.ouverts), 1)

    def test_http_200_ignore_range_sans_concatener(self):
        self.http.side_effect = [ReponseHTTP(headers={"Content-Length": "6"}, chunks=[b"old"]),
                                 ReponseHTTP(headers={"Content-Length": "6"}, chunks=[b"abcdef"])]
        chemin = self.lancer()
        self.assertEqual(self.nas.fichiers[chemin], b"abcdef")
        self.assertEqual(self.http.call_args_list[1].kwargs["headers"]["Range"], "bytes=3-")

    def test_http_206_sans_content_length_utilise_taille_totale_content_range(self):
        self.http.side_effect = [ReponseHTTP(headers={"Content-Length": "6"}, chunks=[b"ab"]),
                                 ReponseHTTP(206, {"Content-Range": "bytes 2-5/6"}, [b"cdef"])]
        chemin = self.lancer()
        self.assertEqual(self.nas.fichiers[chemin], b"abcdef")

    def test_reponses_range_incoherentes_repartent_proprement_de_zero(self):
        for headers in ({"Content-Range": "bytes 1-5/6"},
                        {"Content-Range": "bytes 2-5/6", "Content-Length": "6"},
                        {"Content-Range": "bytes 2-6/7"},
                        {"Content-Range": "bytes 2-5/6", "ETag": '"v2"'},
                        {}):
            with self.subTest(headers=headers):
                self.http.reset_mock()
                self.http.side_effect = [ReponseHTTP(headers={"Content-Length": "6", "ETag": '"v1"'}, chunks=[b"ab"]),
                                         ReponseHTTP(206, headers, [b"incorrect"]),
                                         ReponseHTTP(headers={"Content-Length": "6"}, chunks=[b"abcdef"])]
                chemin = self.lancer()
                self.assertEqual(self.nas.fichiers[chemin], b"abcdef")
                self.assertNotIn("Range", self.http.call_args_list[2].kwargs["headers"])

    def test_taille_depassee_et_content_length_absent_ne_publient_rien(self):
        for headers, chunks in (({"Content-Length": "2"}, [b"trop_long"]), ({}, [b"abc"]),
                                ({"Content-Length": "3", "Content-Encoding": "gzip"}, [b"abc"])):
            with self.subTest(headers=headers):
                self.http.side_effect = None
                self.http.return_value = ReponseHTTP(headers=headers, chunks=chunks)
                self.assertIsNone(self.lancer())
                self.assertEqual(self.nas.ouverts, [])

    def test_http_416_confirme_un_fichier_entier_apres_interruption(self):
        self.http.side_effect = [ReponseHTTP(headers={"Content-Length": "3"}, chunks=[b"abc"], erreur=IncompleteRead(b"", 0)),
                                 ReponseHTTP(416, {"Content-Range": "bytes */3"})]
        chemin = self.lancer()
        self.assertEqual(self.nas.fichiers[chemin], b"abc")

    def test_http_416_incoherent_repart_de_zero(self):
        self.http.side_effect = [ReponseHTTP(headers={"Content-Length": "6"}, chunks=[b"abc"]),
                                 ReponseHTTP(416, {"Content-Range": "bytes */2"}),
                                 ReponseHTTP(headers={"Content-Length": "2"}, chunks=[b"xy"])]
        chemin = self.lancer()
        self.assertEqual(self.nas.fichiers[chemin], b"xy")
        self.assertNotIn("Range", self.http.call_args_list[2].kwargs["headers"])

    def test_timeout_entre_reprises_ne_perd_pas_le_partiel(self):
        self.http.side_effect = [ReponseHTTP(headers={"Content-Length": "6"}, chunks=[b"abc"]),
                                 requests.exceptions.Timeout("coupure"),
                                 ReponseHTTP(206, {"Content-Range": "bytes 3-5/6"}, [b"def"])]
        chemin = self.lancer()
        self.assertEqual(self.nas.fichiers[chemin], b"abcdef")
        for requete in self.http.call_args_list[1:]:
            self.assertEqual(requete.kwargs["headers"]["Range"], "bytes=3-")

    def test_echec_http_cinq_tentatives_backoff_et_aucune_url_signee_dans_logs(self):
        self.http.side_effect = requests.exceptions.Timeout(f"timeout {URL_SIGNEE}")
        self.assertIsNone(self.lancer())
        self.assertEqual(self.http.call_count, 5)
        self.assertEqual(self.sleep.call_args_list, [call(2), call(4), call(8), call(16)])
        self.assertEqual(self.nas.ouverts, [])
        self.assertNotIn("SECRET_A_NE_PAS_LOGGER", str([log.mock_calls for log in self.logs]))

    def test_statut_http_est_logge_sans_url_signee(self):
        self.http.return_value = ReponseHTTP(403)
        self.assertIsNone(self.lancer())
        logs = str([log.mock_calls for log in self.logs])
        self.assertIn("HTTP 403", logs)
        self.assertNotIn("SECRET_A_NE_PAS_LOGGER", logs)
        self.assertEqual(self.nas.ouverts, [])

    def test_temps_local_disque_plein_interrompt_proprement(self):
        with patch(f"{FICHIERS}.tempfile.mkstemp", side_effect=OSError(28, "No space left")):
            self.assertIsNone(self.lancer())
        self.http.assert_not_called()
        self.assertEqual(self.nas.ouverts, [])

    def test_coupure_smb_ou_taille_nas_erronee_reessaie_sans_http(self):
        for erreur in ("erreurs_ecriture", "tailles_fausses", "erreurs_rename"):
            with self.subTest(erreur=erreur):
                self.http.reset_mock()
                self.http.side_effect = None
                self.http.return_value = ReponseHTTP(headers={"Content-Length": "6"}, chunks=[b"abcdef"])
                setattr(self.nas, erreur, 1)
                chemin = self.lancer()
                self.assertEqual(self.nas.fichiers[chemin], b"abcdef")
                self.assertEqual(self.http.call_count, 1)
                self.assertTrue(self.nas.supprimes[-1].endswith(".part"))

    def test_echec_nas_preserve_ancien_fichier_et_nettoie_les_partiels(self):
        chemin = r"\\nas\share\Dossier\Annexes\document.pdf"
        self.nas.fichiers[chemin] = b"ancien_document_complet"
        self.nas.erreurs_ecriture = 5
        self.http.return_value = ReponseHTTP(headers={"Content-Length": "3"}, chunks=[b"abc"])
        self.assertIsNone(self.lancer())
        self.assertEqual(self.nas.fichiers, {chemin: b"ancien_document_complet"})
        self.assertEqual(self.http.call_count, 1)
        self.assertEqual(len(self.nas.ouverts), 5)

    def test_ne_pas_ecraser_un_fichier_existant_et_utiliser_rename_sinon(self):
        chemin = r"\\nas\share\Dossier\Annexes\document.pdf"
        self.nas.fichiers[chemin] = b"existant"
        self.assertIsNone(self.lancer(ecrase=False))
        self.http.assert_not_called()
        del self.nas.fichiers[chemin]
        self.http.return_value = ReponseHTTP(headers={"Content-Length": "3"}, chunks=[b"abc"])
        self.assertEqual(self.lancer(ecrase=False), chemin)
        self.assertEqual(self.nas.fichiers[chemin], b"abc")

    def test_noms_partiels_uniques_entre_appels(self):
        self.http.return_value = ReponseHTTP(headers={"Content-Length": "3"}, chunks=[b"abc"])
        self.lancer()
        self.lancer()
        self.assertEqual(len(set(self.temp_paths)), 2)
        self.assertEqual(len(set(self.nas.ouverts)), 2)

    def test_petite_pj_reussie_ne_produit_pas_de_logs_info(self):
        self.http.return_value = ReponseHTTP(headers={"Content-Length": "3"}, chunks=[b"abc"])

        self.lancer()

        self.logs[0].info.assert_not_called()

