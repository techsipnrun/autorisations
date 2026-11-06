from pathlib import Path
import re
import subprocess
import tempfile
from types import SimpleNamespace
from unittest import skipUnless

from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings
from django.urls import include, path

from autorisations.models.models_generation import Balise
from document_generation.forms import DynamicDocumentForm

urlpatterns=[path('document-generation/',include('document_generation.urls')),path('back-office/',lambda request:HttpResponse(),name='back_office')]
CHROME=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')


@skipUnless(CHROME.exists(),'Chrome absent')
@override_settings(ROOT_URLCONF=__name__)
class NumberInterfaceTests(SimpleTestCase):
    def test_reserver_recuperer_et_modifier_nom_sans_attribution_au_chargement(self):
        src=Path(__file__).resolve().parents[2]
        known=Balise(id=1,code='dossier.numero',libelle='Numéro dossier',type='INTEGER',mode='CONNUE')
        manual=Balise(id=42,code='projet.quantite',libelle='Quantité',type='INTEGER',mode='A_RENSEIGNER')
        html=render_to_string('document_generation/generation_form.html',{
            'dossier':SimpleNamespace(numero=123,id_demarche_id=14,nom_dossier='Test'),
            'document_template':SimpleNamespace(pk=2,nom='Test'),'csrf_token':'test-token',
            'form':DynamicDocumentForm(balises=[manual]),
            'known_form':DynamicDocumentForm(balises=[known],prefix='known',initial={'balise_1':123}),
            'resolved_balises':[{'code':'dossier.numero','libelle':'Numéro dossier','value':123}],
            'numbering_kind':'acte','number_state':{'request_key':'key-1'},
            'filename_pattern':'jeudi_{document.numero}.docx',
            'filename_values':{'document.numero':{'label':'Numéro du document','value':'À générer','pending':True}},
        })
        html=re.sub(r'<link rel="stylesheet"[^>]*>','',html)
        html=re.sub(r'<script src="[^"]*" defer></script>','',html)
        css='\n'.join((src/f'document_generation/static/document_generation/css/{name}.css').read_text(encoding='utf-8') for name in ('generation_form','generation_fields'))
        js=(src/'document_generation/static/document_generation/js/generation_number.js').read_text(encoding='utf-8')
        mock="""
        let requests=0,accepted=false,confirmations=0;
        window.confirm=()=>{confirmations++;return accepted;};
        window.fetch=async(url,options={})=>{
            const response=result=>new Response(JSON.stringify(result),{headers:{'Content-Type':'application/json'}});
            if(url.includes('/numeros/')) {
                if(!document.querySelector('[data-generation-progress]').open) throw new Error('GIF de recherche absent');
                return response({choices:[{key:'d:7:1',numero:'2026-112',dossier:12892949,nature:'Arrêté'}]});
            }
            if(options.headers['X-CSRFToken']!=='test-token') throw new Error('CSRF absent');
            requests++;
            return response({numero:options.body.get('action')==='reserve' ? '2026-011' : '2026-112',selection:'selection-'+requests,request_key:'key-'+(requests+1)});
        };
        """
        scenario="""
        document.addEventListener('DOMContentLoaded',async()=>{
            const result=document.createElement('pre');result.id='result';document.body.append(result);
            const wait=async predicate=>{for(let i=0;i<80;i++){if(predicate())return;await new Promise(resolve=>setTimeout(resolve,20));}throw new Error('Attente expirée');};
            try {
                const control=document.querySelector('[data-document-number]'),editor=document.querySelector('[data-output-editor]');
                const manual=document.querySelector('[name=balise_42]');
                manual.required=true;manual.value='';manual.dispatchEvent(new Event('input',{bubbles:true}));
                if(!control.hidden) throw new Error('Numéro proposé avant les informations obligatoires');
                manual.value='12';manual.dispatchEvent(new Event('input',{bubbles:true}));
                if(control.hidden) throw new Error('Numéro masqué malgré les autres informations valides');
                if(!control.closest('.manual-fields') || control.nextElementSibling?.className!=='actions') throw new Error('Numéro mal placé');
                if(requests!==0 || !editor.querySelector('.is-pending')) throw new Error('Numéro attribué au chargement');
                if(control.querySelector('.number-format-example').hidden) throw new Error('Exemple absent avant attribution');
                control.querySelector('[data-number-reserve]').click();
                if(requests!==0 || confirmations!==1) throw new Error('Confirmation réservation ignorée');
                accepted=true;control.querySelector('[data-number-reserve]').click();
                await wait(()=>requests===1 && !control.querySelector('[data-number-reserve]').disabled);
                if(control.querySelector('[data-number-value]').textContent!=='2026-011' || editor.querySelector('.is-pending')) throw new Error('Numéro non injecté dans la chip');
                if(!control.querySelector('.number-format-example').hidden) throw new Error('Exemple encore affiché après attribution');
                if(!control.querySelector('.number-actions').hidden || editor.querySelector('.output-variable button')) throw new Error('Actions ou suppression de chip encore visibles');
                control.querySelector('[data-number-toggle]').click();
                if(control.querySelector('.number-actions').hidden) throw new Error('Actions non réaffichées');
                control.querySelector('[data-number-recover]').click();
                await wait(()=>control.querySelector('dialog').open);
                const choice=control.querySelector('[data-number-choice]');
                if(choice.options[1].textContent!=='2026-112 (Arrêté - Dossier 12892949)') throw new Error('Choix dossier lié incorrect');
                if(!control.querySelector('[data-number-confirm]').disabled) throw new Error('Confirmation active sans choix');
                control.querySelector('.number-picker-trigger').click();
                if(!control.querySelector('.number-picker-options em')) throw new Error('Métadonnées non italiques');
                control.querySelector('.number-picker-options button').click();
                control.querySelector('[data-number-confirm]').click();
                await wait(()=>requests===2 && !control.querySelector('dialog').open);
                if(control.querySelector('[data-number-value]').textContent!=='2026-112' || !editor.textContent.includes('2026-112')) throw new Error('Numéro récupéré non affiché');
                editor.querySelector('.output-filename-text:last-child').textContent='-corrige';editor.dispatchEvent(new Event('input',{bubbles:true}));
                if(document.querySelector('[name=output_filename]').value!=='jeudi_{document.numero}-corrige.docx') throw new Error('Nom modifié perdu');
                const selection=window.getSelection(),range=document.createRange();range.selectNodeContents(editor);selection.removeAllRanges();selection.addRange(range);
                const deletion=new InputEvent('beforeinput',{inputType:'deleteContentBackward',bubbles:true,cancelable:true});
                editor.dispatchEvent(deletion);if(!deletion.defaultPrevented) throw new Error('Suppression des chips autorisée');
                if(editor.querySelectorAll('[data-variable]').length!==1) throw new Error('Chip disparue');
                if(document.documentElement.scrollWidth>innerWidth+1) throw new Error('Débordement');
                result.textContent='NUMBERS_OK';
            }catch(error){result.textContent=error.stack;}
        });
        """
        html=html.replace('</head>',f'<style>{css}</style></head>').replace('</body>',f'<script>{mock}</script><script>{js}</script><script>{scenario}</script></body>')
        with tempfile.TemporaryDirectory() as temporary:
            page=Path(temporary)/'number.html';page.write_text(html,encoding='utf-8')
            for width in (540,1600):
                with self.subTest(width=width):
                    response=subprocess.run([str(CHROME),'--headless=new','--disable-gpu','--no-first-run','--disable-background-networking',
                        f'--user-data-dir={temporary}/profile-{width}',f'--window-size={width},1000','--virtual-time-budget=5000','--dump-dom',page.as_uri()],
                        capture_output=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
                    dom=response.stdout.decode('utf-8',errors='replace')
                    self.assertIn('<pre id="result">NUMBERS_OK</pre>',dom,re.findall(r'<pre id="result">(.*?)</pre>',dom,re.S))
