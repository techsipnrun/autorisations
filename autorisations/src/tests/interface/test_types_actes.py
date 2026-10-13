"""Navigation et formulaire des types d'actes dans Chrome, sans services réels."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import tempfile
from threading import Thread
from unittest import skipUnless
from urllib.parse import urlsplit

from django.template.loader import render_to_string
from django.test import SimpleTestCase

from autorisations.models.models_documents import DocumentNature
from instruction.forms_types_actes import TypeActeForm


CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


@skipUnless(CHROME.exists(), "Chrome headless n'est pas installé.")
class TypesActesInterfaceTests(SimpleTestCase):
    def test_navigation_formulaire_et_affichage_responsif(self):
        src = Path(__file__).resolve().parents[2]
        nature = DocumentNature(
            id=90, nature="Nouveau type d’acte", est_acte=True,
            prefixe_numero="TEST/", prefixe_nom_fichier="TEST-",
            mode_publication_raa="non_requise", autorise_dm=False,
        )
        html = render_to_string("instruction/back_office.html", {
            "demarches_back_office": [], "csrf_token": "test",
            "formulaires_types_actes": [
                {"type": nature, "form": TypeActeForm(instance=nature, auto_id="acte-90-%s"), "prochain_numero": "2026-1044", "position": 1},
                {"type": DocumentNature(id=91, nature="Autre acte", est_acte=True), "form": TypeActeForm(instance=DocumentNature(est_acte=True), auto_id="acte-91-%s"), "prochain_numero": "2026-1000", "position": 2},
            ],
            "formulaire_nouveau_type_acte": TypeActeForm(instance=DocumentNature(est_acte=True)),
            "premier_numero_acte": "2026-1000",
        })
        script = """
        let orderFails = false;
        window.fetch = async url => url.includes('/ordre/') ? new Response(JSON.stringify(
            orderFails ? {success: false, error: 'Classement refusé'} : {success: true, ordre: [91, 90]}
        ), {status: orderFails ? 400 : 200, headers: {'Content-Type': 'application/json'}}) : new Response(JSON.stringify({errors: {nature: ['Erreur simulée']}}), {
            status: 400, headers: {'Content-Type': 'application/json'},
        });
        const wait = () => new Promise(resolve => setTimeout(resolve, 60));
        window.addEventListener('load', async () => {
            const output = document.createElement('pre');
            output.id = 'browser-test-result';
            document.body.append(output);
            const assert = (ok, message) => { if (!ok) throw new Error(message); };
            try {
                const panel = document.querySelector('[data-panel="types-actes"]');
                assert(!panel.hidden, 'Navigation directe depuis URL');
                assert(!document.getElementById('back-office-circuit-nav').hidden, 'Circuit déplié');
                const circuit = document.querySelector('[data-section="circuit"]');
                circuit.click();
                assert(document.getElementById('back-office-circuit-nav').hidden && !panel.hidden, 'Repli du menu sans changer la page');
                assert(location.hash === '#circuit/types-actes', 'URL préservée au repli');
                circuit.click();
                assert(!document.getElementById('back-office-circuit-nav').hidden, 'Second clic redéplie le menu');
                const cards = panel.querySelectorAll('details');
                assert([...cards].every(card => !card.open), 'Fiches repliées par défaut');
                assert(getComputedStyle(panel.querySelector('.back-office-acte-create')).borderTopColor === 'rgb(0, 0, 0)', 'Bordure noire du bloc d’ajout');
                const card = panel.querySelector('[data-type-acte-id="90"]');
                card.open = true;
                const form = card.querySelector('form');
                assert(form.querySelector('[data-type-acte-preview]').textContent === 'Prochain numéro estimé : TEST/2026-1044', 'Prochain compteur issu du serveur');
                const preview = form.querySelector('.back-office-acte-number-preview');
                assert(!preview.open, 'Explication du numéro repliée par défaut');
                preview.querySelector('summary').click();
                assert(preview.open && card.open, 'Clic déplie seulement l’explication du numéro');
                preview.querySelector('summary').click();
                assert(!preview.open, 'Explication à nouveau repliée');
                assert([...form.querySelectorAll('label')].some(label => label.textContent.trim() === 'Actif *'), 'Libellé Actif');
                assert(form.elements.autorise_dm.value === 'false', 'Dépôt DM désactivé correctement affiché');
                assert(form.elements.mode_publication_raa.value === 'non_requise', 'Mode RAA affiché');
                assert(!form.elements.ordre_affichage, 'Pas de saisie de classement arbitraire');
                assert(form.elements.actif.getBoundingClientRect().width < form.elements.actif.parentElement.getBoundingClientRect().width / 2, 'Liste Oui/Non à sa largeur utile');
                assert(getComputedStyle(form.elements.actif).borderTopColor === 'rgb(0, 0, 0)', 'Bordure noire du select');
                if (CSS.supports('appearance', 'base-select') && CSS.supports('selector(select::picker(select))')) {
                    assert(getComputedStyle(form.elements.actif, '::picker(select)').borderTopColor === 'rgb(0, 0, 0)', 'Bordure noire du menu déroulant');
                }
                assert([...form.querySelectorAll('input:not([type="hidden"]), select')].every(field => field.required), 'Champs obligatoires');
                const icon = card.querySelector('.back-office-collapse-icon-open');
                assert(getComputedStyle(icon).display !== 'none', 'Icône moins visible');
                assert(document.documentElement.scrollWidth <= innerWidth, 'Pas de débordement horizontal');
                const help = form.querySelector('.back-office-acte-help');
                const bubble = help.querySelector('[role="tooltip"]');
                const headingLabel = help.parentElement.querySelector('label');
                const gap = help.getBoundingClientRect().left - headingLabel.getBoundingClientRect().right;
                assert(gap >= 0 && gap <= 9, 'i placé juste à côté du label');
                assert(getComputedStyle(bubble).visibility === 'hidden', 'Aide masquée par défaut');
                help.focus();
                assert(getComputedStyle(bubble).visibility === 'visible', 'Aide accessible au clavier');
                assert(getComputedStyle(help).cursor !== 'help', 'Pas de point d’interrogation au survol');
                const bounds = bubble.getBoundingClientRect();
                assert(bounds.left >= 0 && bounds.right <= innerWidth, 'Infobulle dans la fenêtre');
                help.blur();
                const raaHelp = form.elements.mode_publication_raa.parentElement.querySelector('.back-office-acte-help');
                raaHelp.focus();
                const raaBubble = raaHelp.querySelector('[role="tooltip"]');
                assert(raaBubble.textContent.split(String.fromCharCode(10)).length === 3, 'Trois lignes distinctes pour les modes RAA');
                assert(getComputedStyle(raaBubble).whiteSpace === 'pre-line', 'Retours à la ligne conservés');
                raaHelp.blur();
                form.elements.prefixe_numero.value = 'AUTRE/';
                form.elements.prefixe_numero.dispatchEvent(new Event('input', {bubbles: true}));
                assert(form.querySelector('[data-type-acte-preview]').textContent === 'Prochain numéro estimé : AUTRE/2026-1044', 'Aperçu du préfixe sans réinitialiser le compteur');
                card.querySelector('[data-type-acte-move="descendre"]').click();
                await wait();
                const list = panel.querySelector('[data-type-acte-list]');
                assert(list.firstElementChild.dataset.typeActeId === '91', 'Classement mis à jour sans rechargement');
                assert(card.querySelector('[data-type-acte-rank]').textContent === '2', 'Position mise à jour');
                assert(card.open && form.elements.prefixe_numero.value === 'AUTRE/', 'État ouvert et saisie conservés');
                assert(card.querySelector('[data-type-acte-move="descendre"]').disabled, 'Flèche en limite désactivée');
                orderFails = true;
                card.querySelector('[data-type-acte-move="monter"]').click();
                await wait();
                assert(list.firstElementChild.dataset.typeActeId === '91', 'Classement inchangé en cas d’échec');
                assert(panel.querySelector('[data-type-acte-order-status]').textContent === 'Classement refusé', 'Erreur de classement visible');
                form.dispatchEvent(new Event('submit', {cancelable: true}));
                await wait();
                assert(form.querySelector('[data-type-acte-status]').textContent === 'Erreur simulée', 'Erreur visible près du formulaire');
                assert(!form.querySelector('[type="submit"]').disabled, 'Nouvelle tentative possible');
                document.querySelector('[data-section="services-externes"]').click();
                await wait();
                assert(panel.hidden, 'Navigation vers services');
                document.querySelector('[data-section="types-actes"]').click();
                await wait();
                assert(!panel.hidden && location.hash === '#circuit/types-actes', 'Retour direct vers types d’actes');
                document.querySelector('[data-section="demarche"]').click();
                await wait();
                const menuDemarche = document.querySelector('[data-section="demarche"]');
                const submenuDemarche = document.getElementById('back-office-demarches-nav');
                assert(!submenuDemarche.hidden, 'Démarche déplié au premier clic');
                menuDemarche.click();
                assert(submenuDemarche.hidden && menuDemarche.getAttribute('aria-expanded') === 'false', 'Démarche replié au second clic');
                menuDemarche.click();
                assert(!submenuDemarche.hidden, 'Démarche redéplié');
                document.querySelector('[data-carto-view="cartes"]').click();
                await wait();
                const cartoPanel=document.querySelector('[data-panel="carto"]');
                const cartoMenu=document.querySelector('.back-office-nav-item[data-section="carto"]');
                const cartoNav=document.getElementById('back-office-carto-nav');
                assert(!cartoPanel.hidden&&cartoPanel.dataset.cartoVue==='cartes'&&location.hash==='#carto/cartes','Navigation directe vers Personnaliser les cartes');
                assert(!cartoNav.hidden&&cartoMenu.getAttribute('aria-expanded')==='true','Sous-menu Carto déplié');
                cartoMenu.click();assert(cartoNav.hidden,'Repli du menu Carto sans changer de page');
                cartoMenu.click();assert(!cartoNav.hidden,'Réouverture du menu Carto');
                document.querySelector('[data-carto-view="catalogue"]').click();await wait();
                assert(location.hash==='#carto/catalogue'&&cartoPanel.dataset.cartoVue==='catalogue','Navigation Catalogue');
                window.dispatchEvent(new HashChangeEvent('hashchange'));await wait();
                assert(cartoPanel.dataset.cartoVue==='catalogue','Rubrique restaurée depuis URL');
                const source = document.querySelector('#test-project-source');
                verrouillerNatureProjet(source, 'Nouveau type d’acte');
                const select = document.querySelector('#test-project-nature');
                assert(select.value === '90' && select.disabled, 'Reprise de numéro : sélection du type par identifiant');
                assert(source.querySelector('.nature-acte-verrouillee').value === '90', 'Identifiant transmis au serveur');
                output.textContent = 'TYPES_ACTES_OK';
            } catch (error) { output.textContent = 'TYPES_ACTES_ERROR: ' + error.message; }
        });
        """
        html = html.replace("</head>", '<script src="/static/instruction/js/projet_acte_identique.js" defer></script>' + f"<script>{script}</script></head>")
        html = html.replace("</body>", '''<div hidden>
            <select id="test-project-nature"><option value=""></option><option value="90">Nouveau type d’acte</option></select>
            <div id="test-project-source" data-nature-select="test-project-nature"></div>
        </div></body>''')

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == "/":
                    data, content_type = html.encode("utf-8"), "text/html; charset=utf-8"
                elif path.startswith("/static/instruction/"):
                    resource = src / "instruction/static/instruction" / path.removeprefix("/static/instruction/")
                    if not resource.is_file():
                        self.send_error(404)
                        return
                    data = resource.read_bytes()
                    content_type = "text/css" if resource.suffix == ".css" else "application/javascript" if resource.suffix == ".js" else "application/octet-stream"
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.end_headers()
                self.wfile.write(data)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for width in (540, 1600):
                with self.subTest(width=width), tempfile.TemporaryDirectory() as profile:
                    result = subprocess.run([
                        str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run",
                        "--disable-background-networking", f"--window-size={width},1000",
                        f"--user-data-dir={profile}", "--virtual-time-budget=3000", "--dump-dom",
                        f"http://127.0.0.1:{server.server_port}/#circuit/types-actes",
                    ], capture_output=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
                    dom = result.stdout.decode("utf-8", errors="replace")
                    self.assertIn('<pre id="browser-test-result">TYPES_ACTES_OK</pre>', dom,
                                  dom[dom.rfind('<pre id="browser-test-result">'):][-500:])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
