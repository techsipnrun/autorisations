"""Libellé CS adapté à la largeur réelle du bloc, sans accès aux services métier."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import tempfile
from threading import Thread
from unittest import skipUnless
from urllib.parse import urlsplit

from django.template.loader import render_to_string
from django.test import SimpleTestCase


CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


@skipUnless(CHROME.exists(), "Chrome headless indisponible.")
class LibelleTransmissionCSInterfaceTests(SimpleTestCase):
    def test_libelle_sur_une_ligne_en_lecture_et_edition_dans_les_deux_vues(self):
        src = Path(__file__).resolve().parents[2] / "instruction/static/instruction/css"
        libelle = render_to_string("instruction/refacto/avis_libelle_transmission_cs.html")
        blocs = "".join(f'''<div class="infos-avis" style="width:{largeur}px">
            <p class="date-transmission-cs-valeur">{libelle} 16/10/2026 <button>✎</button></p>
            <form class="form-date-cs"><label>{libelle}</label><input type="date"></form>
            <p>{libelle} 16/10/2026</p></div>''' for largeur in (250, 350, 650))
        pages = {}
        for vue in ("instructeur", "expert"):
            styles = ["instruction_dossier_avis.css", "instruction_dossier_messagerie.css"]
            if vue == "expert":
                styles.append("avis_expert.css")
            styles.append("avis_responsive.css")
            liens = "".join(f'<link rel="stylesheet" href="/{css}">' for css in styles)
            pages[f"/{vue}"] = f'''<!doctype html><html><head><meta charset="utf-8">{liens}</head>
                <body><div class="nav_preinstruction">{blocs}</div><script>
                window.addEventListener('load',()=>{{
                    const sortie=document.createElement('pre');document.body.append(sortie);
                    try {{
                        const assert=(ok,message)=>{{if(!ok)throw new Error(message);}};
                        document.querySelectorAll('.infos-avis').forEach(bloc=>{{
                            const compact=innerWidth<=1400||bloc.clientWidth-32<=430;
                            bloc.querySelectorAll('.avis-transmission-cs-label').forEach(label=>{{
                                const complet=label.querySelector('.avis-transmission-cs-libelle-complet');
                                const court=label.querySelector('.avis-transmission-cs-libelle-court');
                                assert((getComputedStyle(complet).display==='none')===compact,'Libellé adapté au bloc');
                                const visible=compact?court:complet;
                                const range=document.createRange();range.selectNodeContents(visible);
                                assert(range.getClientRects().length===1,'Libellé sur une seule ligne');
                                assert(label.getBoundingClientRect().right<=bloc.getBoundingClientRect().right,'Aucun débordement du libellé');
                            }});
                        }});
                        sortie.textContent='LIBELLE_CS_OK';
                    }} catch(erreur) {{sortie.textContent='ECHEC: '+erreur.message;}}
                }});
                </script></body></html>'''.encode("utf-8")

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                path = urlsplit(self.path).path
                if path in pages:
                    contenu, mime = pages[path], "text/html; charset=utf-8"
                elif path.removeprefix("/") in {"instruction_dossier_avis.css", "instruction_dossier_messagerie.css", "avis_expert.css", "avis_responsive.css"}:
                    contenu, mime = (src / path.removeprefix("/")).read_bytes(), "text/css"
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.end_headers()
                self.wfile.write(contenu)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for vue in ("instructeur", "expert"):
                for largeur in (1000, 1600):
                    with self.subTest(vue=vue, largeur=largeur), tempfile.TemporaryDirectory(prefix="agida-cs-") as profile:
                        resultat = subprocess.run([
                            str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run", "--disable-background-networking",
                            f"--user-data-dir={profile}", f"--window-size={largeur},1000", "--virtual-time-budget=1000", "--dump-dom",
                            f"http://127.0.0.1:{server.server_port}/{vue}",
                        ], capture_output=True, timeout=45, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                        dom = resultat.stdout.decode("utf-8", errors="replace")
                        self.assertIn(">LIBELLE_CS_OK</pre>", dom, dom[-1600:])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
