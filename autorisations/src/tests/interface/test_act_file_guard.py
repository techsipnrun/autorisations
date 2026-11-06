from pathlib import Path
import re
import subprocess
import tempfile
from unittest import skipUnless

from django.test import SimpleTestCase

CHROME = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')


@skipUnless(CHROME.exists(), 'Chrome absent')
class ActFileGuardInterfaceTests(SimpleTestCase):
    def test_blocage_compteur_et_reverification_au_retour(self):
        root = Path(__file__).resolve().parents[2] / 'document_generation/static/document_generation'
        script = (root / 'js/act_file_guard.js').read_text(encoding='utf-8')
        css = (root / 'css/act_file_guard.css').read_text(encoding='utf-8')
        html = '''<!doctype html><meta charset="utf-8"><style>CSS</style>
        <nav class="dossier-actions-menu"><span data-act-repair-count hidden></span></nav>
        <span data-act-history-guard data-status-url="mock" data-repair-url="/generation/#generation-history"></span>
        <form id="act"><div class="projet_acte_pj"><div class="selection-fichier-work"><input name="piece_jointe_work"></div></div><select name="nature_document"><option value="3">Nature</option><option value="4">Autre nature</option></select><div class="projet-acte-identique-option"><input type="checkbox" name="projet_acte_identique"></div><button type="submit">Confirmer</button></form>
        <form id="other"><button>Autre action</button></form>
        <script>
        let status={missing:2,unknown:0,blocked:true};
        window.fetch=async()=>new Response(JSON.stringify(status),{headers:{'Content-Type':'application/json'}});
        </script><script>SCRIPT</script><script>
        document.addEventListener('DOMContentLoaded',async()=>{
            const result=document.createElement('pre');result.id='result';document.body.append(result);
            const wait=async test=>{for(let i=0;i<80;i++){if(test())return;await new Promise(r=>setTimeout(r,20));}throw new Error('Timeout');};
            const refresh=()=>window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}));
            try {
                const badge=document.querySelector('[data-act-repair-count]'),form=document.querySelector('#act');
                await wait(()=>badge.textContent==='2');
                if(!form.querySelector('fieldset').hidden) throw new Error('Formulaire bloqué encore visible');
                if(!form.querySelector('button').matches(':disabled') || !form.querySelector('select').matches(':disabled')) throw new Error('Formulaire non bloqué');
                if(document.querySelector('#other button').matches(':disabled')) throw new Error('Autre action bloquée');
                if(form.querySelector('.act-history-guard-notice').hidden || !form.querySelector('a').href.endsWith('#generation-history')) throw new Error('Réparation inaccessible');
                const event=new Event('submit',{bubbles:true,cancelable:true});form.dispatchEvent(event);if(!event.defaultPrevented) throw new Error('Soumission non bloquée');
                status={missing:0,unknown:1,blocked:true};refresh();await wait(()=>badge.textContent==='!');
                if(!form.querySelector('button').matches(':disabled') || !form.querySelector('.act-history-guard-notice').textContent.includes('impossible')) throw new Error('Indisponibilité non bloquante');
                status={missing:0,unknown:0,blocked:false,recognized_files:[{filename:'projet.docx',nature_id:3,description:'Projet généré par Louis CALU'}]};refresh();await wait(()=>badge.hidden);
                if(form.querySelector('button').matches(':disabled') || !form.querySelector('.act-history-guard-notice').hidden) throw new Error('Réparation non débloquante');
                if(form.querySelector('fieldset').hidden) throw new Error('Formulaire réparé encore masqué');
                const file=form.querySelector('input'),nature=form.querySelector('select'),info=form.querySelector('.generated-act-provenance');
                file.value='projet.docx';file.dispatchEvent(new Event('change',{bubbles:true}));
                if(info.hidden || !info.textContent.includes('Louis CALU')) throw new Error('Provenance absente');
                if(!form.querySelector('.projet-acte-identique-option').hidden) throw new Error('Option numéro partagé non masquée');
                nature.value='4';nature.dispatchEvent(new Event('change',{bubbles:true}));
                if(info.hidden || !info.classList.contains('is-mismatch') || !form.querySelector('button').disabled) throw new Error('Mauvaise nature non bloquée');
                nature.value='3';file.value='manuel.docx';file.dispatchEvent(new Event('change',{bubbles:true}));if(!info.hidden) throw new Error('Provenance sur fichier manuel');
                if(form.querySelector('.projet-acte-identique-option').hidden || form.querySelector('button').disabled) throw new Error('Parcours manuel non restauré');
                status={missing:0,unknown:0,blocked:false,recognized_files:[
                    {filename:'projet.docx',document_id:7,nature_id:3,numero:'2026-0123',active:false,replaceable:true,description:'Nouvelle version'},
                    {filename:'ancien.docx',document_id:9,nature_id:3,numero:'2026-0123',active:true,replaceable:true,description:'Ancienne version'}]};
                file.value='projet.docx';refresh();
                await wait(()=>!form.querySelector('.generated-act-replacement').hidden);
                const consent=form.querySelector('.generated-act-replacement input'),replacementId=form.querySelector('[name=generated_act_replace_id]');
                if(!form.querySelector('button').disabled || replacementId.value) throw new Error('Remplacement autorisé sans consentement');
                consent.checked=true;consent.dispatchEvent(new Event('change',{bubbles:true}));
                if(form.querySelector('button').disabled || replacementId.value!=='9') throw new Error('Consentement non pris en compte');
                file.value='manuel.docx';file.dispatchEvent(new Event('change',{bubbles:true}));
                if(replacementId.value || consent.checked) throw new Error('Consentement conservé pour un autre fichier');
                result.textContent='GUARD_OK';
            } catch(error) {result.textContent=error.stack;}
        });</script>'''.replace('CSS', css).replace('SCRIPT', script)
        with tempfile.TemporaryDirectory() as temporary:
            page = Path(temporary) / 'guard.html'
            page.write_text(html, encoding='utf-8')
            response = subprocess.run([str(CHROME), '--headless=new', '--disable-gpu', '--no-first-run',
                '--disable-background-networking', f'--user-data-dir={temporary}/profile',
                '--virtual-time-budget=5000', '--dump-dom', page.as_uri()],
                capture_output=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
            dom = response.stdout.decode('utf-8', errors='replace')
            self.assertIn('<pre id="result">GUARD_OK</pre>', dom, re.findall(r'<pre id="result">(.*?)</pre>', dom, re.S))
