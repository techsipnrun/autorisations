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
    def test_three_information_blocks_compact_responsive_and_missing_border(self):
        agida=Balise(id=1,code='dossier.numero',libelle='Numéro du dossier',type='TEXT',source='AGIDA',mode='CONNUE')
        source=Balise(id=2,code='form.commune',libelle='Commune du projet',type='TEXT',source='FORMULAIRE',mode='CONNUE')
        missing=Balise(id=3,code='form.date',libelle='Date du projet',type='DATE',source='FORMULAIRE',mode='CONNUE',required=True)
        manual=Balise(id=4,code='texte',libelle='Commentaire',type='TEXT',source='MANUELLE',mode='A_RENSEIGNER',required=True)
        html=render_to_string('document_generation/generation_form.html',{
            'form':DynamicDocumentForm(balises=[missing,manual]),
            'known_form':DynamicDocumentForm(balises=[agida,source],prefix='known',initial={'balise_1':'123','balise_2':'Saint-Paul'}),
            'resolved_balises':[{'code':'dossier.numero','libelle':agida.libelle,'value':'123'},
                                {'code':'form.commune','libelle':source.libelle,'value':'Saint-Paul'}],
            'dossier':SimpleNamespace(numero=123),'document_template':SimpleNamespace(nom='Test'),
        })
        src=Path(__file__).resolve().parents[2]
        css='\n'.join((src/f'document_generation/static/document_generation/css/{name}.css').read_text(encoding='utf-8') for name in ['generation_form','generation_fields'])
        html=re.sub(r'<link rel="stylesheet"[^>]*>','',html).replace('</head>',f'<style>{css}</style></head>')
        scenario='''<script>
        const result=document.createElement('pre');result.id='result';document.body.append(result);
        try {
            const form=document.querySelector('#generation-form');
            const blocks=[...form.querySelectorAll('[data-information-block]')];
            if(blocks.length!==3) throw Error('Three blocks missing');
            if(blocks[0].textContent.includes('Saint-Paul') || !blocks[1].textContent.includes('Saint-Paul')) throw Error('Sources mixed');
            if(!blocks[1].classList.contains('has-missing-information') || !blocks[2].classList.contains('has-missing-information')) throw Error('Missing border absent');
            if(blocks[0].classList.contains('has-missing-information')) throw Error('Filled block orange');
            const field=form.elements.balise_3;if(!blocks[1].contains(field)) throw Error('Missing source in manual block');
            field.value='2026-11-18';field.dispatchEvent(new Event('input',{bubbles:true}));
            if(blocks[1].classList.contains('has-missing-information')) throw Error('Border not cleared');
            const row=blocks[0].querySelector('.information-value');
            const label=row.querySelector('dt').getBoundingClientRect(),value=row.querySelector('dd').getBoundingClientRect();
            if(innerWidth>900 && Math.abs(label.top-value.top)>2) throw Error('Value below label');
            if(document.documentElement.scrollWidth>innerWidth+1) throw Error('Horizontal overflow');
            blocks[1].querySelector('.edit-known').click();
            if(!blocks[0].querySelector('[data-known-editor]').hidden || blocks[0].querySelector('[data-known-display]').hidden) throw Error('AGIDA editing changed with formulaire');
            const source=form.elements['known-balise_2'];source.value='Saint-Denis';
            const sourceRow=source.closest('.field'),sourceLabel=sourceRow.querySelector('label');
            if(innerWidth>900) {
                sourceLabel.style.maxWidth='110px';sourceLabel.textContent='Un libelle suffisamment long sur plusieurs lignes :';
                const labelBox=sourceLabel.getBoundingClientRect(),inputBox=source.getBoundingClientRect();
                if(Math.abs((labelBox.top+labelBox.bottom-inputBox.top-inputBox.bottom)/2)>3) throw Error('Multiline label alignment');
            }
            if(parseFloat(getComputedStyle(source).paddingTop)>5) throw Error('Input padding too large');
            blocks[1].querySelector('[data-known-save]').click();
            if(new FormData(form).has('known-balise_1')) throw Error('Unedited AGIDA submitted');
            if(!blocks[1].querySelector('[data-known-display]').textContent.includes('Saint-Denis')) throw Error('Edit source lost');
            result.textContent='GROUPS_OK';
        } catch(error) {result.textContent=error.stack;}
        </script>'''
        html=html.replace('</body>',scenario+'</body>')
        with tempfile.TemporaryDirectory() as temporary:
            page=Path(temporary)/'groups.html';page.write_text(html,encoding='utf-8')
            for width in (390,1600):
                response=subprocess.run([str(CHROME),'--headless=new','--disable-gpu','--no-first-run',
                    '--disable-background-networking',f'--window-size={width},1000',f'--user-data-dir={temporary}/profile-{width}',
                    '--virtual-time-budget=2000','--dump-dom',page.as_uri()],capture_output=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
                dom=response.stdout.decode('utf-8',errors='replace')
                self.assertEqual(re.findall(r'<pre id="result">(.*?)</pre>',dom,re.S),['GROUPS_OK'])

    def test_conditional_required_fields_and_preserved_values(self):
        definitions = [Balise(id=i, code=code, libelle=code, type=kind, required=True, mode='A_RENSEIGNER')
                       for i, code, kind in [(1, 'a', 'BOOLEAN'), (2, 'b', 'BOOLEAN'), (3, 'x', 'TEXT'), (4, 'y', 'TEXT')]]
        rules = {'b': ['value', 'a'], 'x': ['or', ['value', 'a'], ['value', 'b']],
                 'y': ['and', ['value', 'a'], ['value', 'b']]}
        html = render_to_string('document_generation/generation_form.html', {
            'form': DynamicDocumentForm(balises=definitions), 'known_form': DynamicDocumentForm(prefix='known'),
            'dossier': SimpleNamespace(numero=1), 'document_template': SimpleNamespace(nom='Test'),
            'generation_conditions': {'rules': rules, 'values': {}},
        })
        scenario = '''<script>
        const form=document.querySelector('#generation-form');
        const result=document.createElement('pre');result.id='result';document.body.append(result);
        const input=n=>form.elements['balise_'+n];
        const row=n=>input(n).closest('.field');
        const set=(n,value)=>{input(n).value=value;input(n).dispatchEvent(new Event('change',{bubbles:true}));};
        try {
            if(!row(2).hidden || !row(3).hidden || !row(4).hidden) throw Error('Initial visibility');
            set(1,'true');
            if(row(2).hidden || row(3).hidden || !row(4).hidden) throw Error('Nested controller / or');
            set(2,'true');if(row(4).hidden) throw Error('Nested field');
            set(3,'Saved');set(4,'Detail');
            if(!form.checkValidity()) throw Error('Visible form invalid');
            set(2,'false');if(!row(4).hidden || !input(4).disabled) throw Error('Hidden required active');
            set(2,'true');if(input(4).value!=='Detail') throw Error('Value lost');
            set(1,'false');set(2,'false');
            if(!row(3).hidden || !form.checkValidity()) throw Error('Hidden fields block validation');
            result.textContent='CONDITIONS_OK';
        } catch(error) {result.textContent=error.stack;}
        </script>'''
        html = html.replace('</body>', scenario+'</body>')
        with tempfile.TemporaryDirectory() as temporary:
            page=Path(temporary)/'conditions.html';page.write_text(html,encoding='utf-8')
            response=subprocess.run([str(CHROME),'--headless=new','--disable-gpu','--no-first-run',
                '--disable-background-networking',f'--user-data-dir={temporary}/profile',
                '--virtual-time-budget=2000','--dump-dom',page.as_uri()],capture_output=True,timeout=45,
                creationflags=subprocess.CREATE_NO_WINDOW)
            dom=response.stdout.decode('utf-8',errors='replace')
            self.assertEqual(re.findall(r'<pre id="result">(.*?)</pre>',dom,re.S),['CONDITIONS_OK'])

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
