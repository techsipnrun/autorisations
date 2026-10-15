"""Placement adaptatif des identités et du nom, avec les vrais templates et CSS."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import tempfile
from threading import Thread
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth.models import User
from django.template import Context, Template
from django.test import SimpleTestCase


CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


@skipUnless(CHROME.exists(), "Chrome headless indisponible.")
class EnteteDossierInterfaceTests(SimpleTestCase):
    def test_blocs_cote_a_cote_et_retour_a_la_ligne(self):
        src = Path(__file__).resolve().parents[2]
        demarche = SimpleNamespace(type="Travaux")
        personne = SimpleNamespace(nom="Calu", prenom="Louis", email="louis@example.test")
        cas = []
        for fichier in ("instruction_dossier", "preinstruction_dossier"):
            source = (src / f"instruction/templates/instruction/{fichier}.html").read_text(encoding="utf-8")
            # Isoler l'en-tête réel sans rendre les autres rubriques métier du dossier.
            fragment = source.split('<div class="identites-dossier">', 1)[1].split("{% for champ in champs %}", 1)[0]
            fragment = fragment.split('<div class="champs">', 1)[0]
            template = Template('{% load static group_tags %}<div class="identites-dossier">' + fragment)
            for nombre in (3, 2):
                with patch("instruction.templatetags.group_tags._instructeur_for_user", return_value=object()):
                    rendu = template.render(Context({
                        "request": SimpleNamespace(user=User(username="test", is_superuser=True)),
                        "demarche": demarche,
                        "dossier": SimpleNamespace(numero=123456, nom_affiche="Un projet à Mafate", id_demarche=demarche),
                        "beneficiaire": personne,
                        "demandeur_intermediaire": personne if nombre == 3 else None,
                    }))
                cas.append(f'<section data-nombre="{nombre}">{rendu}</section>')
        css = (src / "instruction/static/instruction/css/dossier.css").read_text(encoding="utf-8")
        script = """
        window.addEventListener('load', () => {
            const sortie=document.createElement('pre');document.body.append(sortie);
            const assert=(ok,message)=>{if(!ok) throw new Error(message);};
            try {
                for(const zone of document.querySelectorAll('section')) {
                    const groupe=zone.querySelector('.identites-dossier');
                    const blocs=Array.from(groupe.children);
                    assert(blocs.length===Number(zone.dataset.nombre),'Nom et identités dans le même groupe');
                    for(const largeur of [1600,1000,480,280]) {
                        zone.style.width=largeur+'px';
                        const limite=groupe.getBoundingClientRect();
                        for(const bloc of blocs) {
                            const rect=bloc.getBoundingClientRect();
                            assert(rect.right<=limite.right+1,'Bloc contenu à '+largeur+'px');
                            for(const contenu of bloc.querySelectorAll('h2, p:not(.nom-dossier-info-bulle), .nom_dossier_ligne')) {
                                if(!contenu.getClientRects().length) continue;
                                assert(contenu.getBoundingClientRect().right<=rect.right+1,'Contenu sans débordement à '+largeur+'px');
                            }
                        }
                        const lignes=new Set(blocs.map(bloc=>Math.round(bloc.getBoundingClientRect().top)));
                        if(largeur===1600) {
                            assert(lignes.size===1,'Tous les blocs côte à côte sur grande largeur');
                            const nom=groupe.querySelector('.nom_du_dossier');
                            const identite=groupe.querySelector('.identite_demandeur');
                            assert(nom.getBoundingClientRect().height<identite.getBoundingClientRect().height,'Le nom conserve sa hauteur naturelle');
                        }
                        if(largeur===280) assert(lignes.size===blocs.length,'Blocs empilés sur petite largeur');
                    }
                    for(const p of groupe.querySelectorAll('.identite_demandeur p')) p.textContent='organisation.tres.longue'.repeat(15);
                    groupe.querySelector('.nom_du_dossier').classList.add('is-editing');
                    for(const bloc of blocs) {
                        for(const contenu of bloc.querySelectorAll('p, input, button')) {
                            if(!contenu.getClientRects().length) continue;
                            assert(contenu.getBoundingClientRect().right<=bloc.getBoundingClientRect().right+1,'Longs textes et édition contenus');
                        }
                    }
                }
                sortie.textContent='ENTETE_DOSSIER_OK';
            } catch(erreur) { sortie.textContent='ENTETE_DOSSIER_ERREUR: '+erreur.message; }
        });
        """
        html = f'<!doctype html><html><head><meta charset="utf-8"><style>{css}</style><script>{script}</script></head><body>{"".join(cas)}</body></html>'

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
            with tempfile.TemporaryDirectory(prefix="agida-entete-") as profile:
                resultat = subprocess.run([
                    str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run", "--disable-background-networking",
                    f"--user-data-dir={profile}", "--window-size=1800,1000", "--virtual-time-budget=1000", "--dump-dom",
                    f"http://127.0.0.1:{server.server_port}/",
                ], capture_output=True, timeout=45, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                dom = resultat.stdout.decode("utf-8", errors="replace")
                self.assertTrue('>ENTETE_DOSSIER_OK</pre>' in dom, dom[-2000:])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
