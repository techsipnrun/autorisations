"""Les libellés des documents restent sur une ligne sans masquer les actions."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import tempfile
from threading import Thread
from types import SimpleNamespace
from unittest import skipUnless

from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import SimpleTestCase

from autorisations.models.models_documents import Document, DocumentNature


CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


@skipUnless(CHROME.exists(), "Chrome headless indisponible.")
class DocumentsDossierInterfaceTests(SimpleTestCase):
    def test_libelles_sans_retour_a_la_ligne_sur_petits_ecrans(self):
        src = Path(__file__).resolve().parents[2]
        lignes = []
        for nature, prefixe in (("Courrier", "C-"), ("Arrêté directeur", "DIR-I-"), ("Délibération CA", "CA-")):
            doc = Document(id=1, numero="2026-1002", emplacement="Dossier/Work/",
                           titre="document_avec_un_titre_particulierement_long_" * 5 + ".pdf",
                           id_nature=DocumentNature(nature=nature, prefixe_numero=prefixe))
            for template in ("document_copy_row", "document_download_row"):
                lignes.append('<ul class="test-documents">' + render_to_string(f"instruction/refacto/{template}.html", {
                    "doc": doc, "show_numero": True, "show_copy_path": True,
                    "request": SimpleNamespace(user=AnonymousUser()),
                }) + '</ul>')
        css = "\n".join((src / f"instruction/static/instruction/css/{nom}.css").read_text(encoding="utf-8")
                        for nom in ("dossier", "instruction_dossier", "dossier_manif_sportive"))
        reference = "CourrierTEST-2020-929/LC/JDP"
        for classe in ("numero-acte", "reference-acte-manuelle"):
            lignes.append(f'<div class="test-numerotation validant {classe}"><label>Numéro de l’acte :</label><input type="text" value="{reference}" size="{len(reference) + 3}" readonly></div>')
        script = """
        window.addEventListener('load',()=>{
            const sortie=document.createElement('pre');document.body.append(sortie);
            const assert=(ok,message)=>{if(!ok) throw new Error(message);};
            try {
                for(const largeur of [240,320,480,900]) {
                    for (const zone of document.querySelectorAll('.test-numerotation')) {
                        zone.style.width=largeur+'px';
                        const champ=zone.querySelector('input');
                        assert(champ.getBoundingClientRect().right<=zone.getBoundingClientRect().right+1, 'Saisie du numéro sans débordement à '+largeur+'px');
                        assert(parseFloat(getComputedStyle(champ).paddingLeft)>=8, 'Saisie avec padding');
                        if (largeur>=480) assert(champ.scrollWidth<=champ.clientWidth+1, 'Référence longue entièrement visible à '+largeur+'px');
                    }
                    for(const zone of document.querySelectorAll('.test-documents')) {
                        zone.style.width=largeur+'px';
                        const titre=zone.querySelector('.doc-titre-no-download');
                        assert(titre.getBoundingClientRect().height<30,'Libellé sur une seule ligne à '+largeur+'px');
                        assert(titre.scrollWidth<=titre.clientWidth+1,'Libellé et numéro jamais tronqués à '+largeur+'px');
                        assert(getComputedStyle(titre).textOverflow!=='ellipsis','Pas de points de suspension sur le libellé');
                        const ligne=zone.querySelector('.doc-copy-row, .doc-download-row');
                        assert(ligne.getBoundingClientRect().right<=zone.getBoundingClientRect().right+1,'Document sans débordement à '+largeur+'px');
                        for(const action of zone.querySelectorAll('.doc-copy-icon-control, .document-download-link, .document-apercu-trigger, .document-copy-trigger')) {
                            assert(action.getBoundingClientRect().right<=zone.getBoundingClientRect().right+1,'Action accessible à '+largeur+'px');
                        }
                        if(largeur===900) {
                            const fichier=zone.querySelector('.doc-fichier-titre, .document-titre');
                            assert(Math.abs(titre.getBoundingClientRect().top-fichier.getBoundingClientRect().top)<10,'Fichier et libellé côte à côte si la place suffit');
                            assert(fichier.clientWidth<fichier.scrollWidth,'Seul le fichier long est tronqué');
                        }
                    }
                }
                sortie.textContent='DOCUMENTS_DOSSIER_OK';
            } catch(erreur) { sortie.textContent='DOCUMENTS_DOSSIER_ERREUR: '+erreur.message; }
        });
        """
        html = f'<!doctype html><html><head><meta charset="utf-8"><style>{css}.test-documents{{padding:0;list-style:none;}}</style><script>{script}</script></head><body>{"".join(lignes)}</body></html>'

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode("utf-8") if self.path == "/" else b"")

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="agida-documents-") as profile:
                resultat = subprocess.run([
                    str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run", "--disable-background-networking",
                    f"--user-data-dir={profile}", "--window-size=1000,900", "--virtual-time-budget=1000", "--dump-dom",
                    f"http://127.0.0.1:{server.server_port}/",
                ], capture_output=True, timeout=45, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                dom = resultat.stdout.decode("utf-8", errors="replace")
                self.assertTrue('>DOCUMENTS_DOSSIER_OK</pre>' in dom, dom[-2000:])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
