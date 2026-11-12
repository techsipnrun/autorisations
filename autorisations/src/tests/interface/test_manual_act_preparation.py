from pathlib import Path
import re
import subprocess
import tempfile
from types import SimpleNamespace
from unittest import skipUnless

from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings
from django.urls import path

urlpatterns = [path('instruction/<int:num_dossier>/preparer-acte/', lambda request: HttpResponse(), name='prepare_manual_act')]
CHROME = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')


@skipUnless(CHROME.exists(), 'Chrome absent')
@override_settings(ROOT_URLCONF=__name__)
class ManualActPreparationInterfaceTests(SimpleTestCase):
    def test_choix_reservation_recuperation_annulation_et_trois_formulaires(self):
        root = Path(__file__).resolve().parents[2]
        partial = render_to_string('instruction/refacto/manual_act_preparation.html', {
            'dossier':SimpleNamespace(numero=123), 'csrf_token':'test-token'})
        partial = re.sub(r'<(?:link|script)\b[^>]*>(?:</script>)?', '', partial)
        forms = ''.join(f'''<form id="step-{index}">
            <select name="nature_document"><option value="">Nature</option><option value="3">Arrêté directeur</option><option value="4">Délibération CA</option><option value="6" data-numerotation="manuelle">Courrier</option></select>
            <div class="projet_acte_pj"><input name="piece_jointe_work" value="projet.docx"><div class="selection-fichier-work"><ul class="liste-work-files"></ul></div></div>
            <div class="projet-acte-identique-option"><input type="checkbox" name="projet_acte_identique"><input name="numero_reference" disabled></div>
            <button type="submit">Confirmer</button></form>''' for index in range(3))
        css=(root/'instruction/static/instruction/css/manual_act_preparation.css').read_text(encoding='utf-8')
        css+=(root/'document_generation/static/document_generation/css/act_file_guard.css').read_text(encoding='utf-8')
        app=(root/'instruction/static/instruction/js/manual_act_preparation.js').read_text(encoding='utf-8')
        guard=(root/'document_generation/static/document_generation/js/act_file_guard.js').read_text(encoding='utf-8')
        setup='''
        let active=null,posts=0,accepted=false,copied='',historyFiles=[{filename:'projet.docx',nature_id:3,numero:'2026-0012',description:'Projet généré',document_id:10}];
        window.confirm=()=>accepted;
        Object.defineProperty(navigator,'clipboard',{value:{writeText:async value=>{copied=value;}}});
        const natures=[{id:3,label:'Arrêté directeur',automatic:true,can_generate:true,url:'/document-generation/dossier/123/?demarche=7&template=10'},
            {id:4,label:'Délibération CA',automatic:true,can_generate:true,url:'/document-generation/dossier/123/?demarche=7'},
            {id:6,label:'Courrier',automatic:false,can_generate:false,url:'/generation/'},{id:5,label:'Avis simple',automatic:true,can_generate:false,url:'/document-generation/dossier/123/?demarche=7'}];
        window.fetch=async(url,options={})=>{
            const response=data=>new Response(JSON.stringify(data),{headers:{'Content-Type':'application/json'}});
            if(String(url).includes('/history/')) return response({missing:0,unknown:0,blocked:false,recognized_files:historyFiles});
            if(String(url).includes('?nature=')) return response({choices:[{key:'d:8:1',display:'DIR-I-2026-0011',numero:'2026-0011',dossier:456}]});
            if(options.method==='POST'){
                posts++;const body=options.body;
                if(body.get('csrfmiddlewaretoken')!=='test-token' || body.get('confirmed')!=='1') throw new Error('Confirmation ou CSRF absent');
                if(body.get('action')==='cancel') active=null;
                else active={id:'preparation-1',nature_id:Number(body.get('nature')),nature:'Arrêté directeur',numero:body.get('action')==='manual'?body.get('numero'):body.get('action')==='recover'?'2026-0011':'2026-0012',display:body.get('action')==='manual'?body.get('numero'):body.get('action')==='recover'?'DIR-I-2026-0011':'DIR-I-2026-0012',origin:body.get('action')==='recover'?'RECUPERE':'GENERE',dossiers:[456]};
            }
            return response({natures,preparation:active});
        };
        '''
        scenario='''
        document.addEventListener('DOMContentLoaded',async()=>{
            const result=document.getElementById('result');
            const wait=async predicate=>{for(let i=0;i<100;i++){if(predicate())return;await new Promise(resolve=>setTimeout(resolve,20));}throw new Error('Attente expiree');};
            try{
                const block=document.querySelector('[data-manual-act]'),get=name=>block.querySelector(`[data-preparation-${name}]`);
                await wait(()=>!get('config').hidden);
                const picker=document.querySelector('.act-nature-picker'),tooltip=document.querySelector('.prepared-number-help');
                picker.querySelector('.act-nature-trigger').click();
                const blocked=picker.querySelector('[data-blocked-nature]');
                if(!blocked || blocked.getAttribute('aria-disabled')!=='true') throw new Error('Nature grisee absente');
                picker.querySelector('.act-nature-trigger').dispatchEvent(new Event('pointerover',{bubbles:true}));
                if(!tooltip.hidden) throw new Error('Aide visible hors option grisee');
                const originalValue=document.querySelector('form select').value;blocked.click();
                if(document.querySelector('form select').value!==originalValue) throw new Error('Nature grisee selectionnable');
                blocked.dispatchEvent(new Event('pointerover',{bubbles:true}));
                if(tooltip.hidden || tooltip.hasAttribute('title')) throw new Error('Aide option absente');
                const bounds=tooltip.getBoundingClientRect();
                if(bounds.left<0 || bounds.right>innerWidth || bounds.top<0 || bounds.bottom>innerHeight) throw new Error('Aide hors ecran');
                picker.querySelector('.act-nature-trigger').click();
                const nature=get('nature');
                nature.value='3';nature.dispatchEvent(new Event('change'));
                if(get('options').hidden || !get('generate').getAttribute('href').includes('template=10')) throw new Error('Template unique non propose');
                nature.value='4';nature.dispatchEvent(new Event('change'));
                if(get('generate').getAttribute('href').includes('template=')) throw new Error('Plusieurs templates preselectionnes');
                nature.value='5';nature.dispatchEvent(new Event('change'));
                if(!get('options').hidden || get('number-options').hidden) throw new Error('Mode manuel automatique absent');
                nature.value='3';nature.dispatchEvent(new Event('change'));get('manual').click();
                get('reserve').click();if(posts!==0) throw new Error('Reservation sans accord');
                accepted=true;get('reserve').click();get('reserve').click();
                await wait(()=>!get('current').hidden);
                if(posts!==1 || !get('config').hidden || get('number').textContent!=='DIR-I-2026-0012') throw new Error('Reservation incorrecte');
                const noDraft=document.querySelector('[data-no-draft-advice]');
                if(!noDraft.disabled || !noDraft.dataset.numberHelp.includes('Brouillon') || noDraft.hasAttribute('title')) throw new Error('Etape avis sans brouillon debloquee par numero');
                for(const form of document.querySelectorAll('form')) {
                    if(form.querySelector('select').disabled || form.querySelector('select').value!=='3' || form.querySelector('[name=manual_preparation]').value!=='preparation-1') throw new Error('Integration formulaire absente');
                    if(form.querySelector('.act-nature-picker').nextElementSibling!==form.querySelector('[data-manual-preparation-summary]')) throw new Error('Resume avant menu nature');
                    if(!form.querySelector('.projet-acte-identique-option').hidden || !form.querySelector('[name=projet_acte_identique]').disabled) throw new Error('Ancien partage encore actif');
                }
                get('copy').click();await wait(()=>copied==='DIR-I-2026-0012');
                historyFiles.push({filename:'autre.docx',nature_id:4,numero:'2026-0099',description:'Autre nature',document_id:11});
                window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}));
                await wait(()=>!document.querySelector('form select option[value="4"]').disabled);
                for(const form of document.querySelectorAll('form')) {
                    const select=form.querySelector('select');select.value='4';select.dispatchEvent(new Event('change',{bubbles:true}));
                    form.querySelector('[name=piece_jointe_work]').value='autre.docx';form.dispatchEvent(new Event('change'));
                    if(!form.querySelector('[data-manual-preparation-summary]').hidden || form.querySelector('[name=manual_preparation]') || form.dataset.manualPreparationNumber) throw new Error('Reservation autre nature appliquee');
                    if(form.querySelector('button[type=submit]').disabled) throw new Error('Autre nature generee bloquee');
                    select.value='3';select.dispatchEvent(new Event('change',{bubbles:true}));
                    form.querySelector('[name=piece_jointe_work]').value='projet.docx';form.dispatchEvent(new Event('change'));
                    if(form.querySelector('[data-manual-preparation-summary]').hidden || !form.querySelector('[name=manual_preparation]')) throw new Error('Reservation non restauree pour sa nature');
                }
                get('cancel').click();await wait(()=>get('current').hidden);
                if(nature.value!=='' || posts!==2) throw new Error('Annulation incorrecte');
                for(const form of document.querySelectorAll('form')) if(form.querySelector('[name=manual_preparation]') || form.querySelector('select').disabled) throw new Error('Ancienne preparation conservee');
                nature.value='3';nature.dispatchEvent(new Event('change'));get('manual').click();get('recover').click();
                await wait(()=>get('dialog').open);
                if(!get('confirm').disabled || !get('choice').options[1].textContent.includes('456')) throw new Error('Choix recuperation incorrect');
                get('choice').value='d:8:1';get('choice').dispatchEvent(new Event('change'));get('confirm').click();
                await wait(()=>!get('current').hidden);
                if(!get('used').textContent.includes('456') || get('dialog').open) throw new Error('Provenance recuperation absente');
                await wait(()=>[...document.querySelectorAll('form')].every(form=>form.querySelector('button[type=submit]').disabled));
                for(const form of document.querySelectorAll('form')) {
                    if(!form.querySelector('button[type=submit]').disabled || !form.querySelector('.generated-act-provenance').textContent.includes('numéro réservé')) throw new Error('Conflit numero genere non bloque');
                    form.querySelector('[name=piece_jointe_work]').value='manuel.docx';form.dispatchEvent(new Event('change'));
                    if(form.querySelector('button[type=submit]').disabled) throw new Error('Projet manuel bloque apres correction');
                    const reminder=form.querySelector('.generated-act-provenance');
                    if(reminder.hidden || !reminder.classList.contains('is-manual-reminder') || reminder.querySelector('strong')?.textContent!=='DIR-I-2026-0011') throw new Error('Rappel manuel absent ou numero non gras');
                    if(form.querySelector('[data-manual-preparation-summary] strong')?.textContent!=='DIR-I-2026-0011') throw new Error('Numero du resume non gras');
                }
                get('cancel').click();await wait(()=>get('current').hidden);
                historyFiles=[];window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}));
                await wait(()=>document.querySelector('[data-requires-numbered-nature]').disabled);
                const manualOption=[...document.querySelector('form select').options].find(option=>option.value==='6');
                if(!manualOption.disabled) throw new Error('Nature manuelle sans reference non grisee');
                nature.value='6';nature.dispatchEvent(new Event('change'));
                if(!get('reserve').hidden || get('enter').hidden) throw new Error('Saisie manuelle indisponible');
                get('enter').click();get('entry').value='COURRIER/42/Texte';get('entry').dispatchEvent(new Event('input'));
                get('entry-confirm').click();await wait(()=>!get('current').hidden);
                if(get('number').textContent!=='COURRIER/42/Texte' || get('entry-dialog').open) throw new Error('Reference saisie perdue');
                if(document.querySelector('[data-requires-numbered-nature]').disabled || manualOption.disabled) throw new Error('Etape non debloquee par reference saisie');
                if(document.documentElement.scrollWidth>innerWidth) throw new Error('Debordement');
                result.textContent='MANUAL_ACT_OK';
            }catch(error){result.textContent=error.stack;}
        });
        '''
        html=f'''<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head><body>{partial}<span data-act-repair-count hidden></span><button data-requires-numbered-nature>Changer</button><button data-requires-numbered-nature data-no-draft-advice disabled>Avis CS</button>{forms}
            <div data-act-history-guard data-status-url="/history/" data-repair-url="/repair/"></div><pre id="result"></pre>
            <script>{setup}</script><script>{guard}</script><script>{app}</script><script>{scenario}</script></body></html>'''
        with tempfile.TemporaryDirectory() as temporary:
            page=Path(temporary)/'manual.html';page.write_text(html,encoding='utf-8')
            for width in (540,1600):
                with self.subTest(width=width):
                    response=subprocess.run([str(CHROME),'--headless=new','--disable-gpu','--no-first-run','--disable-background-networking',
                        f'--user-data-dir={temporary}/profile-{width}',f'--window-size={width},1000','--virtual-time-budget=8000',
                        '--dump-dom',page.as_uri()],capture_output=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
                    dom=response.stdout.decode('utf-8',errors='replace')
                    self.assertEqual(re.findall(r'<pre id="result">(.*?)</pre>',dom,re.S),['MANUAL_ACT_OK'])
