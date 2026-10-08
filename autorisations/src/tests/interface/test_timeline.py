"""Vérifie l'atténuation de tous les boutons dans Chrome headless."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import tempfile
from threading import Thread
from unittest import skipUnless

from django.template.loader import render_to_string
from django.test import SimpleTestCase


CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


@skipUnless(CHROME.exists(), "Chrome headless n'est pas installé.")
class TimelineInterfaceTests(SimpleTestCase):
    def test_tous_les_boutons_sont_attenues_sans_affecter_navbar_et_timeline(self):
        src = Path(__file__).resolve().parents[2]
        timeline = render_to_string("instruction/timeline.html", {"numero_dossier": 31770683})
        css = "\n".join((src / f"instruction/static/instruction/css/{nom}.css").read_text(encoding="utf-8")
                        for nom in ("dossier", "dossiers_lies", "timeline"))
        pages = "".join(f"""
            <main class='{classe}' style='margin:100px 10px 20px 120px;height:200px'>
                <div class='formulaire' style='position:relative;height:160px'>
                    <div class='notification-agents-wrapper'><button class='btn-notifier-agents'>Cloche</button></div>
                    <div class='dossiers-liens-trigger-wrapper'><button class='btn-notifier-agents btn-lier-dossiers'>Lien</button></div>
                    <button class='btn-copy-dossier'>Copier</button>
                </div>
            </main>""" for classe in ("page_instruction_dossier", "page_preinstruction_dossier"))
        script = """
        window.addEventListener('load', () => {
            const output = document.createElement('pre'); document.body.append(output);
            const assert = (ok, message) => { if (!ok) throw new Error(message); };
            const sidebar = document.getElementById('left-sidebar');
            const buttons = [...document.querySelectorAll('.btn-notifier-agents, .btn-copy-dossier')];
            const at = el => {
                const r = el.getBoundingClientRect();
                return document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
            };
            const effectiveOpacity = el => {
                let opacity = 1;
                for (let current = el; current; current = current.parentElement) {
                    opacity *= Number(getComputedStyle(current).opacity);
                }
                return opacity;
            };
            try {
                buttons.forEach(b => assert(at(b) === b, 'Bouton accessible avant ouverture'));
                buttons.forEach(b => assert(effectiveOpacity(b) === 1, 'Bouton non atténué avant ouverture'));
                sidebar.dispatchEvent(new Event('mouseenter'));
                buttons.forEach(b => assert(Math.abs(effectiveOpacity(b) - 0.2) < 0.001, 'Bouton atténué y compris avec z-index élevé'));
                assert(effectiveOpacity(sidebar) === 1, 'Timeline non atténuée');
                assert(effectiveOpacity(document.getElementById('test-navbar')) === 1, 'Navbar non atténuée');
                assert(document.elementFromPoint(5, 20).id === 'test-navbar', 'Navbar reste au premier plan');
                assert(sidebar.contains(document.elementFromPoint(5, 100)), 'Timeline reste au premier plan');
                sidebar.dispatchEvent(new Event('mouseleave'));
                buttons.forEach(b => assert(at(b) === b, 'Bouton accessible après fermeture'));
                buttons.forEach(b => assert(effectiveOpacity(b) === 1, 'Bouton non atténué après fermeture'));
                output.textContent = 'TIMELINE_INTERFACE_OK';
            } catch (error) { output.textContent = 'TIMELINE_INTERFACE_ERROR: ' + error.message; }
        });
        """
        html = (f"<html><head><meta charset='utf-8'><style>{css}\n"
                "#test-navbar{position:fixed;inset:0 0 auto;height:80px;background:white;z-index:10000;}"
                f"</style><script>{script}</script></head><body><nav id='test-navbar'></nav>{timeline}{pages}</body></html>")

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
            for largeur in (540, 1600):
                with self.subTest(largeur=largeur), tempfile.TemporaryDirectory(prefix="agida-timeline-") as profile:
                    browser = subprocess.run([
                        str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run",
                        "--disable-background-networking", f"--window-size={largeur},1000",
                        f"--user-data-dir={profile}", "--virtual-time-budget=1000", "--dump-dom",
                        f"http://127.0.0.1:{server.server_port}/",
                    ], capture_output=True, timeout=45, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    output = browser.stdout.decode("utf-8", errors="replace")
                    diagnostic = output[-2000:] or browser.stderr.decode("utf-8", errors="replace")[-2000:]
                    self.assertIn('>TIMELINE_INTERFACE_OK</pre>', output, diagnostic)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
