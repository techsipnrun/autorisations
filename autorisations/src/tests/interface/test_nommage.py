"""Test de l'éditeur dans Chrome headless, avec des réponses API simulées."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import re
import tempfile
from threading import Thread
from types import SimpleNamespace
from unittest import skipUnless

from django.template.loader import render_to_string
from django.test import SimpleTestCase

from synchronisation.utils.nom_dossier import ATTRIBUTS_NOM_DOSSIER, TRANSFORMATIONS_NOM_DOSSIER


CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


@skipUnless(CHROME.exists(), "Chrome headless n'est pas installé.")
class NommageInterfaceTests(SimpleTestCase):
    def test_editeur_priorites_save_apercu_et_recalcul(self):
        src = Path(__file__).resolve().parents[2]
        demarche = SimpleNamespace(id=1, nommage_script_id="test-nommage", nommage_donnees={
            "regles": [], "champs": [{"id": 12, "nom": "Lieu", "type": "text"}],
            "champs_dm": [{"name": "date_debut_evenement", "nom": "Début de l'événement", "type": "datetime"}],
            "attributs": ATTRIBUTS_NOM_DOSSIER, "transformations": TRANSFORMATIONS_NOM_DOSSIER,
        })
        page = render_to_string("instruction/back_office.html", {"demarches_back_office": [demarche], "csrf_token": "test"})
        block = re.search(r'(<details class="back-office-config-block back-office-nommage-block">.*?</details>)', page, re.S).group(1)
        script = """
        window.confirm = () => true;
        const sent = [];
        let failSave = false;
        window.fetch = async (url, options) => {
            sent.push({url, payload: JSON.parse(options.body)});
            if (failSave && url.endsWith('/noms/')) {
                return new Response(JSON.stringify({error: 'Erreur de sauvegarde simulée'}), {
                    status: 400, headers: {'Content-Type': 'application/json'},
                });
            }
            const value = url.includes('apercu') ? {
                nom_genere: 'Denis HOARAU', nom_affiche: 'Nom manuel', nom_manuel: 'Nom manuel',
                details: [{ordre: 1, libelle: 'Personne physique', statut: 'retenue', manquants: []}],
            } : url.includes('recalculer') ? {total: 10, modifies: 5, noms_prioritaires: 2} : {success: true};
            return new Response(JSON.stringify(value), {headers: {'Content-Type': 'application/json'}});
        };
        const wait = () => new Promise(resolve => setTimeout(resolve, 30));
        window.addEventListener('load', async () => {
            const output = document.createElement('pre');
            document.body.append(output);
            const assert = (ok, message) => { if (!ok) throw new Error(message); };
            const byTitle = title => [...document.querySelectorAll('button')].find(button => button.title === title);
            try {
                const namingBlock = document.querySelector('.back-office-nommage-block');
                const info = document.querySelector('.bo-nommage-info');
                assert(getComputedStyle(info).display === 'none', 'Aide masquée si bloc replié');
                namingBlock.open = true;
                assert(getComputedStyle(info).display !== 'none', 'Aide visible si bloc ouvert');
                info.focus();
                await wait();
                assert(getComputedStyle(document.querySelector('.bo-nommage-info-bulle')).visibility === 'visible', 'Infobulle au clavier');
                info.click();
                assert(namingBlock.open, 'Aide sans replier le bloc');
                info.blur();
                document.querySelector('[data-nommage-add]').click();
                document.querySelectorAll('.bo-nommage-rule-icon').forEach(button => {
                    const icon = button.querySelector('svg').getBoundingClientRect();
                    const padding = getComputedStyle(button).padding;
                    assert(icon.width >= 20 && icon.height >= 20 && padding === '3px',
                        `Taille icône ${button.title} : ${icon.width}×${icon.height}px, padding ${padding}`);
                });
                assert(document.querySelector('.bo-nommage-rule').classList.contains('is-unsaved'), 'Nouvelle règle non enregistrée');
                assert(!document.querySelector('.bo-nommage-rule-unsaved').hidden, 'Rappel dans la règle');
                assert(document.querySelector('[data-nommage-save-feedback]').textContent === '', 'Pas de rappel global');
                const toggleStyle = getComputedStyle(document.querySelector('.bo-nommage-rule-toggle'));
                assert(toggleStyle.cursor === 'pointer', 'Curseur modifier/réduire');
                const sharedStyle = getComputedStyle(document.querySelector('#shared-collapse-icon'));
                ['color', 'backgroundColor', 'fontSize', 'fontWeight', 'width', 'height'].forEach(property => {
                    assert(toggleStyle[property] === sharedStyle[property], 'Style commun du bouton : ' + property);
                });
                byTitle('Ajouter une variable').click();
                let select = document.querySelector('.bo-nommage-element select');
                select.value = 'attribut:demandeur.nom';
                select.dispatchEvent(new Event('change'));
                assert(document.querySelector('.bo-nommage-source-field > span').textContent === 'Info BDD', 'Source BDD identifiée');
                const transform = document.querySelector('.bo-nommage-transform');
                transform.value = 'majuscules';
                transform.dispatchEvent(new Event('change'));
                assert(document.querySelector('.bo-nommage-token').textContent.endsWith('(MAJUSCULES)'), 'Transformation entre parenthèses');
                byTitle('Dupliquer la règle').click();
                assert(document.querySelectorAll('.bo-nommage-rule').length === 2, 'Duplication');
                [...document.querySelectorAll('button')].find(button => button.title === 'Monter la règle' && !button.disabled).click();
                assert(document.querySelectorAll('.bo-nommage-priority')[0].textContent === 'Priorité 1', 'Priorités');
                document.querySelector('[data-nommage-number]').value = '123';
                document.querySelector('[data-nommage-preview]').click();
                await wait();
                assert(!document.querySelector('[data-nommage-result]').hidden, 'Aperçu visible');
                assert(document.querySelector('[data-nommage-result]').textContent.includes('Nom manuel'), 'Priorité manuelle');
                const recalculate = document.querySelector('[data-nommage-recalculate]');
                assert(recalculate.disabled, 'Recalcul bloqué si non enregistré');
                document.querySelector('[data-nommage]').dispatchEvent(new Event('submit', {cancelable: true}));
                await wait();
                assert(!recalculate.disabled, 'Recalcul après enregistrement');
                assert(!document.querySelector('.is-unsaved'), 'Rappels effacés après enregistrement');
                assert([...document.querySelectorAll('.bo-nommage-rule-actions')].every(actions => actions.hidden), 'Actions masquées au repli');
                assert(document.querySelector('.bo-nommage-rule-toggle svg'), 'Crayon pour modifier une règle');
                assert(sent.find(call => call.url.endsWith('/noms/')).payload.regles[0].elements[0].transformation === 'majuscules', 'Configuration envoyée');
                document.querySelector('.bo-nommage-rule-toggle').click();
                assert(!document.querySelector('.bo-nommage-rule-actions').hidden, 'Actions visibles en modification');
                const nameInput = document.querySelector('.bo-nommage-rule-name-input');
                nameInput.value = 'Nom modifié';
                nameInput.dispatchEvent(new Event('input'));
                assert(document.querySelectorAll('.is-unsaved').length === 1, 'Seule la règle modifiée est signalée');
                nameInput.value = '';
                nameInput.dispatchEvent(new Event('input'));
                assert(!document.querySelector('.is-unsaved'), 'Retour à la valeur enregistrée');
                select = document.querySelector('.bo-nommage-element select');
                select.value = 'champ:12';
                select.dispatchEvent(new Event('change'));
                assert(document.querySelector('.bo-nommage-source-field > span').textContent === 'Champ formulaire DN', 'Champ DN identifié');
                assert(document.querySelector('.bo-nommage-token').textContent === 'Lieu (MAJUSCULES)', 'Variable DN sans préfixe');
                select.value = 'champ_dm:date_debut_evenement';
                select.dispatchEvent(new Event('change'));
                assert(document.querySelector('.bo-nommage-token--dm').textContent.startsWith('DM · '), 'Variable DM identifiée');
                assert(getComputedStyle(document.querySelector('.bo-nommage-token--dm')).color !==
                    getComputedStyle(document.querySelectorAll('.bo-nommage-token')[1]).color, 'Couleur DM distincte');
                failSave = true;
                document.querySelector('[data-nommage]').dispatchEvent(new Event('submit', {cancelable: true}));
                await wait();
                assert(document.querySelectorAll('.is-unsaved').length === 1 && recalculate.disabled, 'Erreur : modifications conservées');
                failSave = false;
                document.querySelector('[data-nommage]').dispatchEvent(new Event('submit', {cancelable: true}));
                await wait();
                assert(!document.querySelector('.is-unsaved') && !recalculate.disabled, 'Enregistrement confirmé');
                document.querySelector('.bo-nommage-rule-toggle').click();
                const customTransform = document.querySelector('.bo-nommage-transform');
                customTransform.value = 'personnalisee';
                customTransform.dispatchEvent(new Event('change'));
                assert(document.querySelector('.bo-nommage-custom-transform').hidden, 'Transformation personnalisée repliée par défaut');
                byTitle('Modifier la transformation personnalisée').click();
                assert(!document.querySelector('.bo-nommage-custom-transform').hidden, 'Éditeur personnalisé déplié');
                const mappingInputs = document.querySelectorAll('.bo-nommage-custom-row input');
                mappingInputs[0].value = 'Oui';
                mappingInputs[0].dispatchEvent(new Event('input'));
                mappingInputs[1].value = 'Mafate';
                mappingInputs[1].dispatchEvent(new Event('input'));
                const fallbackSelect = document.querySelector('.bo-nommage-custom-fallback select');
                fallbackSelect.value = 'ignorer_regle';
                fallbackSelect.dispatchEvent(new Event('change'));
                byTitle('Réduire la transformation personnalisée').click();
                assert(document.querySelector('.bo-nommage-custom-transform').hidden, 'Éditeur personnalisé replié');
                assert(document.querySelector('.bo-nommage-token').textContent.endsWith('(Personnalisée)'), 'Composition personnalisée');
                document.querySelector('[data-nommage-preview]').click();
                await wait();
                const preview = sent.filter(call => call.url.includes('apercu')).at(-1);
                const mapping = preview.payload.regles[0].elements[0].configuration_transformation;
                assert(mapping.correspondances[0].valeur === 'Oui' && mapping.correspondances[0].texte === 'Mafate', 'Correspondances dans aperçu');
                assert(mapping.sans_correspondance === 'ignorer_regle', 'Choix sans correspondance');
                document.querySelector('[data-nommage]').dispatchEvent(new Event('submit', {cancelable: true}));
                await wait();
                document.querySelector('.bo-nommage-rule-toggle').click();
                assert(document.querySelector('.bo-nommage-custom-transform').hidden, 'Transformation repliée après enregistrement');
                byTitle('Modifier la transformation personnalisée').click();
                assert(document.querySelectorAll('.bo-nommage-custom-row input')[1].value === 'Mafate', 'Correspondance après enregistrement');
                recalculate.click();
                await wait();
                assert(document.querySelector('[data-nommage-status]').textContent.includes('10 dossier'), 'Résultat recalcul');
                assert(document.querySelector('[data-nommage-loader]').hidden, 'Chargement terminé');
                output.textContent = 'NOMMAGE_INTERFACE_OK';
            } catch (error) { output.textContent = 'NOMMAGE_INTERFACE_ERROR: ' + error.message; }
        });
        """
        html = ("<!doctype html><html><head><meta charset='utf-8'>"
                "<link rel='stylesheet' href='/css'><script src='/editor' defer></script>"
                f"<script>{script}</script></head><body><span id='shared-collapse-icon' class='back-office-collapse-icon'>+</span>"
                f"<main style='max-width:900px;margin:auto'>{block}</main></body></html>")
        resources = {
            "/": ("text/html", html.encode()),
            "/editor": ("application/javascript", (src / "instruction/static/instruction/js/back_office_nommage.js").read_bytes()),
            "/css": ("text/css", (src / "instruction/static/instruction/css/back_office.css").read_bytes()),
        }

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                content_type, content = resources.get(self.path, ("image/svg+xml", b"<svg xmlns='http://www.w3.org/2000/svg'/>"))
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="agida-nommage-browser-") as profile:
                browser = subprocess.run([
                    str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run", "--window-size=540,900",
                    "--disable-background-networking", f"--user-data-dir={profile}",
                    "--virtual-time-budget=5000", "--dump-dom", f"http://127.0.0.1:{server.server_port}/",
                ], capture_output=True, timeout=45, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                output = browser.stdout.decode("utf-8", errors="replace")
                diagnostic = output[-5000:] or browser.stderr.decode("utf-8", errors="replace")[-3000:]
                self.assertIn('>NOMMAGE_INTERFACE_OK</pre>', output, diagnostic)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
