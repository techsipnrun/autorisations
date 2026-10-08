"""Contrôle des filtres de reprise de numéro dans un navigateur, sans API."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import tempfile
from threading import Thread
from types import SimpleNamespace
from unittest import skipUnless

from django.template.loader import render_to_string
from django.test import SimpleTestCase


CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


@skipUnless(CHROME.exists(), "Chrome headless n'est pas installé.")
class RechercheProjetActeInterfaceTests(SimpleTestCase):
    def test_filtres_sans_debordement_dans_les_deux_formulaires(self):
        src = Path(__file__).resolve().parents[2]
        contexte = {
            "dossier": SimpleNamespace(id=1, numero=29859769),
            "doc": SimpleNamespace(id=2, id_nature=SimpleNamespace(nature="Arrêté directeur")),
            "types_demarches": ["Une démarche dont le libellé est particulièrement long"],
            "demandeur": SimpleNamespace(id=3),
            "demandeur_affichage": "Une organisation avec un nom particulièrement long " * 4,
        }
        formulaires = "".join(
            "<div class='test-container zone-envoyer-pour-validation show'>"
            + render_to_string(f"instruction/refacto/{nom}.html", contexte) + "</div>"
            for nom in ("projet_acte_identique_option", "recherche_numero_projet_inline")
        )
        css = "\n".join((src / f"instruction/static/instruction/css/{nom}.css").read_text(encoding="utf-8")
                        for nom in ("dossier", "instruction_dossier"))
        script = """
        window.addEventListener('load', () => {
            const output = document.createElement('pre'); document.body.append(output);
            const assert = (ok, message) => { if (!ok) throw new Error(message); };
            document.querySelectorAll('[hidden]').forEach(el => el.hidden = false);
            try {
                for (const width of [160, 260, 480, 900]) {
                    document.querySelectorAll('.test-container').forEach(container => {
                        container.style.width = Math.min(width, window.innerWidth - 32) + 'px';
                        const grid = container.querySelector('.recherche-projet-filtres');
                        const bounds = grid.getBoundingClientRect();
                        assert(grid.scrollWidth <= grid.clientWidth + 1, 'Grille déborde pour ' + width);
                        grid.querySelectorAll('label, input, select, button').forEach(el => {
                            const r = el.getBoundingClientRect();
                            assert(r.right <= bounds.right + 1 && r.left >= bounds.left - 1,
                                   el.tagName + ' déborde pour ' + width);
                        });
                    });
                }
                output.textContent = 'RECHERCHE_PROJET_INTERFACE_OK';
            } catch (error) { output.textContent = 'RECHERCHE_PROJET_INTERFACE_ERROR: ' + error.message; }
        });
        """
        html = (f"<html><head><meta charset='utf-8'><style>{css}\n"
                ".test-container{box-sizing:border-box;padding:8px;margin:0;}"
                f"</style><script>{script}</script></head><body>{formulaires}</body></html>")

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode("utf-8") if self.path == "/" else b"")

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for largeur in (360, 800, 1600):
                with self.subTest(largeur=largeur), tempfile.TemporaryDirectory(prefix="agida-recherche-acte-") as profile:
                    browser = subprocess.run([
                        str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run",
                        "--disable-background-networking", f"--window-size={largeur},1000",
                        f"--user-data-dir={profile}", "--virtual-time-budget=1000", "--dump-dom",
                        f"http://127.0.0.1:{server.server_port}/",
                    ], capture_output=True, timeout=45, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    output = browser.stdout.decode("utf-8", errors="replace")
                    diagnostic = output[-2000:] or browser.stderr.decode("utf-8", errors="replace")[-2000:]
                    self.assertIn('>RECHERCHE_PROJET_INTERFACE_OK</pre>', output, diagnostic)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
