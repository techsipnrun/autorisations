"""Interface du POST d'aperçu dans Chrome, sans serveur, BDD ou NAS."""
from pathlib import Path
import base64
import re
import subprocess
import tempfile
from types import SimpleNamespace
from unittest import skipUnless

from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings
from django.urls import path

from autorisations.models.models_generation import Balise
from document_generation.forms import DynamicDocumentForm

urlpatterns = [path("back-office/", lambda request: HttpResponse(), name="back_office")]
CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


@skipUnless(CHROME.exists(), "Chrome absent")
@override_settings(ROOT_URLCONF=__name__)
class GenerationPreviewInterfaceTests(SimpleTestCase):
    def test_iframe_valeurs_et_action_post_desactivation(self):
        definition = Balise(id=42, code="projet.quantite", libelle="Quantité", type="INTEGER",
                            mode="A_RENSEIGNER", required=True, allow_blank=False)
        repeated = Balise(id=57, code='projet.noms', libelle='Noms', type='LIST', mode='A_RENSEIGNER',
                         source='MANUELLE', libelle_element='Nom', required=False)
        form = DynamicDocumentForm(balises=[definition,repeated], initial={"balise_42": 15})
        known = Balise(id=1, code="dossier.numero", libelle="Numéro", type="INTEGER",
                       mode="CONNUE", required=True, allow_blank=False)
        known_form = DynamicDocumentForm(balises=[known], prefix="known", initial={"balise_1": 30769307})
        context = {
            "dossier": SimpleNamespace(numero=30769307, nom_dossier="Test"),
            "document_template": SimpleNamespace(nom="Modèle de test"), "form": form,
            "known_form": known_form,
            "resolved_balises": [{"code": "dossier.numero", "libelle": "Numéro", "value": 30769307}],
            "preview_exists": True, "preview_url": "about:blank", "csrf_token": "test-token",
            "scroll_position": {"x": 0, "y": 600},
        }
        html = render_to_string("document_generation/generation_form.html", context)
        src = Path(__file__).resolve().parents[2]
        css = (src / "document_generation/static/document_generation/css/generation_form.css").read_text(encoding="utf-8")
        css += (src / "document_generation/static/document_generation/css/generation_fields.css").read_text(encoding="utf-8")
        html = re.sub(r'<link rel="stylesheet"[^>]*>', '', html)
        html = html.replace("</head>", f"<style>{css}</style></head>")
        pages = [("standalone", html)]
        demarche = SimpleNamespace(pk=7, type="Travaux", numero=123)
        shell_context = {**context, "demarches_generation": [demarche, SimpleNamespace(pk=8, type="Agriculture")],
                         "selected_demarche": demarche, "templates_generation": [SimpleNamespace(pk=3, nom="Modèle de test")],
                         "etape_actuelle": SimpleNamespace(etape="En instruction"),
                         "breadcrumb_items": [{"label": "Dossier", "url": "/instruction/30769307/"}, {"label": "Génération de fichier", "url": ""}],
                         "request": SimpleNamespace(path="/document-generation/", user=SimpleNamespace(is_superuser=True))}
        with override_settings(ROOT_URLCONF="autorisations.urls"):
            shell = render_to_string("document_generation/dossier_generation.html", shell_context)
        css_paths = ["instruction/static/instruction/css/" + name + ".css" for name in
                     ("dossier", "instruction_dossier", "navbar", "timeline", "breadcrumb")]
        css_paths.append("document_generation/static/document_generation/css/dossier_generation.css")
        css_paths.append("document_generation/static/document_generation/css/generation_fields.css")
        shell_css = "\n".join((src / path).read_text(encoding="utf-8") for path in css_paths)
        shell = re.sub(r'<link rel="stylesheet"[^>]*>', '', shell)
        shell = shell.replace("</head>", f"<style>{shell_css}</style></head>", 1)
        pages.append(("dossier", shell))
        scenario = """
        document.addEventListener('DOMContentLoaded', async () => {
            const result=document.createElement('pre');result.id='result';document.body.append(result);
            try {
                await new Promise(resolve=>setTimeout(resolve,50));
                if(Math.abs(window.scrollY-600)>1) throw new Error('Scroll non restauré');
                const form=document.querySelector('#generation-form');
                const generate=form.querySelector('[value="generate_file"]'),preview=document.querySelector('[value="preview_pdf"]');
                if(generate.disabled || preview.disabled) throw new Error('Actions désactivées malgré le formulaire valide');
                form.elements.balise_42.value='';form.elements.balise_42.dispatchEvent(new Event('input',{bubbles:true}));
                if(!generate.disabled || !preview.disabled) throw new Error('Actions actives malgré un champ obligatoire vide');
                const field=form.elements.balise_42.closest('.field');
                if(!field.classList.contains('needs-attention') || field.querySelector('[data-field-status]').hidden) throw new Error('Champ manquant non signalé');
                form.elements.balise_42.value='15';form.elements.balise_42.dispatchEvent(new Event('input',{bubbles:true}));
                if(generate.disabled || preview.disabled) throw new Error('Actions non réactivées après saisie');
                if(field.classList.contains('needs-attention') || !field.querySelector('[data-field-status]').hidden) throw new Error('Indicateur conservé après saisie valide');
                if(!document.querySelector('iframe') || form.elements.balise_42.value!=='15') throw new Error('Aperçu ou valeurs absents');
                if(document.documentElement.scrollWidth>innerWidth+1) throw new Error('Débordement horizontal');
                const pencil=document.querySelector('.edit-known');
                const warned=() => {
                    const event=new Event('beforeunload', {cancelable:true});
                    window.dispatchEvent(event);
                    return event.defaultPrevented;
                };
                if(warned()) throw new Error('Alerte sur page intacte');
                form.elements.balise_42.value='16';
                if(!warned()) throw new Error('Saisie manuelle non protégée');
                form.elements.balise_42.value='15';
                const labelTop=document.querySelector('#known-display dt').getBoundingClientRect().top+window.scrollY;
                if(new FormData(form).has('known-balise_1')) throw new Error('Valeur connue soumise hors édition');
                pencil.click();
                if(document.querySelector('#known-editor').hidden) throw new Error('Edition masquée');
                if(Math.abs(document.querySelector('#known-editor label').getBoundingClientRect().top+window.scrollY-labelTop)>1) throw new Error('Label déplacé');
                form.elements['known-balise_1'].value='123';
                if(!warned()) throw new Error('Correction non protégée');
                form.querySelector('[data-known-cancel]').click();
                if(new FormData(form).has('known-balise_1')) throw new Error('Annulation édition ignorée');
                if(form.elements['known-balise_1'].value!=='30769307' || warned()) throw new Error('Annulation ne restaure pas la valeur');
                pencil.click();
                form.elements['known-balise_1'].value='123';
                form.querySelector('[data-known-save]').click();
                if(!document.querySelector('#known-editor').hidden || document.querySelector('#known-display dd').textContent!=='123') throw new Error('Enregistrement non affiché');
                if(!warned()) throw new Error('Correction enregistrée non protégée');
                pencil.click();
                form.elements['known-balise_1'].value='456';
                form.querySelector('[data-known-cancel]').click();
                if(new FormData(form).get('known-balise_1')!=='123') throw new Error('Correction enregistrée perdue après annulation');
                let confirmation='';
                window.confirm=message => {confirmation=message; return false;};
                const link=document.querySelector('main > a') || document.querySelector('.breadcrumb a');
                const click=new MouseEvent('click', {bubbles:true, cancelable:true, button:0});
                link.dispatchEvent(click);
                if(!click.defaultPrevented || !confirmation.includes('abandonner la génération')) throw new Error('Navigation non protégée');
                const demarche=document.querySelector('[data-generation-demarche]');
                if(demarche) {
                    const template=document.querySelector('[data-generation-template]');
                    if(innerWidth>=1200 && Math.abs(template.getBoundingClientRect().top-demarche.getBoundingClientRect().top)>1) throw new Error('Menus non alignés malgré la largeur disponible');
                    if(demarche.getBoundingClientRect().width>document.querySelector('.generation-selection').getBoundingClientRect().width*.9) throw new Error('Menu trop large');
                    demarche.focus();demarche.value='8';demarche.dispatchEvent(new Event('change'));
                    if(demarche.value!=='7') throw new Error('Changement de démarche non annulé');
                    if(!document.querySelector('#left-sidebar') || !document.querySelector('.mini_timeline')) throw new Error('Navigation dossier absente');
                    if(document.querySelector('.nav_preinstruction') || document.querySelector('.dropdown-arrow')) throw new Error('Actions dossier présentes');
                }
                const repeat=form.querySelector('[data-repeated-text]');
                repeat.querySelector('input').value='DUPONT';
                repeat.querySelector('[data-add-row]').click();
                repeat.querySelectorAll('input')[1].value='MARTIN';
                repeat.querySelector('[data-add-row]').click();
                repeat.querySelectorAll('[data-remove-row]')[2].click();
                if(repeat.querySelectorAll('input').length!==2 || repeat.querySelectorAll('input')[1].id!=='id_balise_57_2') throw new Error('Lignes non ajoutées ou renumérotées');
                if(repeat.querySelector('[data-row-number]').textContent!=='1') throw new Error('Numérotation incorrecte');
                const submissionScroll=Math.round(window.scrollY);
                form.addEventListener('submit', event => {
                    event.preventDefault();
                    try {
                        const data=new FormData(form);
                        if(data.get('action')!=='preview_pdf' || data.get('balise_42')!=='15') throw new Error('Action ou valeurs perdues');
                        if(data.get('edit_known')!=='1' || data.get('known-balise_1')!=='123') throw new Error('Correction connue perdue');
                        if(JSON.stringify(data.getAll('balise_57'))!==JSON.stringify(['DUPONT','MARTIN'])) throw new Error('Liste répétable perdue');
                        const overlay=document.querySelector('[data-generation-progress]');
                        if(!overlay.open || !overlay.matches(':modal')) throw new Error('Chargement non bloquant');
                        const bounds=overlay.getBoundingClientRect();
                        if(bounds.width<innerWidth-1 || bounds.height<innerHeight-1) throw new Error('Chargement pas plein écran');
                        if(data.get('_scroll_y')!==String(submissionScroll)) throw new Error('Scroll non transmis');
                        const spinner=document.querySelector('[data-generation-progress] img');
                        if(!spinner.complete || !spinner.naturalWidth) throw new Error('GIF de chargement invalide');
                        if(!document.querySelector('button[form="generation-form"]').disabled) throw new Error('Bouton aperçu non désactivé');
                        if([...form.querySelectorAll('button[type="submit"]')].some(b=>!b.disabled)) throw new Error('Double-clic possible');
                        result.textContent='PREVIEW_OK';
                    } catch(error) {result.textContent=error.stack;}
                });
                document.querySelector('button[form="generation-form"][value="preview_pdf"]').click();
            } catch(error) {result.textContent=error.stack;}
        });
        """
        with tempfile.TemporaryDirectory() as temporary:
            for mode, page_html in pages:
                gif = base64.b64encode((src / "document_generation/static/document_generation/img/loading.gif").read_bytes()).decode("ascii")
                page_html = page_html.replace('/static/document_generation/img/loading.gif', 'data:image/gif;base64,' + gif)
                head, tail = page_html.rsplit("</body>", 1)
                page = Path(temporary) / f"preview-{mode}.html"
                page.write_text(head + f'<div style="height:1000px"></div><script>{scenario}</script></body>' + tail, encoding="utf-8")
                for width in (540, 1600):
                    with self.subTest(mode=mode, width=width):
                        result = subprocess.run([
                            str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run", "--disable-background-networking",
                            f"--user-data-dir={temporary}/profile-{mode}-{width}", f"--window-size={width},1000",
                            "--virtual-time-budget=3000", "--dump-dom", page.as_uri(),
                        ], capture_output=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
                        dom = result.stdout.decode("utf-8", errors="replace")
                        self.assertTrue('<pre id="result">PREVIEW_OK</pre>' in dom, re.findall(r'<pre id="result">(.*?)</pre>', dom, re.S) or dom[-800:])
