"""Le chargement ne commence qu'après une soumission autorisée."""
from pathlib import Path
import re
import subprocess
import tempfile
from unittest import skipUnless
from django.test import SimpleTestCase

CHROME = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')


@skipUnless(CHROME.exists(), 'Chrome absent')
class EtapeLoadingTests(SimpleTestCase):
    def test_chargement_validation_annulation_garde_et_double_envoi(self):
        script = (Path(__file__).resolve().parents[2] / 'instruction/static/instruction/js/actions_dossier.js').read_text(encoding='utf-8')
        html = '''<div id="envoi-acte-attente" hidden><strong id="attente-action-titre"></strong><span id="attente-action-detail"></span></div>
        <div class="zone-envoyer-pour-validation"><form id="avis"><input required name="valideur"><button>Confirmer</button></form></div>
        <form id="autre"><button>Autre action</button></form>
        <script>''' + script + '''</script><script>
        const result=document.createElement('pre');result.id='result';document.body.append(result);
        const overlay=document.querySelector('#envoi-acte-attente'),form=document.querySelector('#avis');
        window.addEventListener('submit',event=>event.preventDefault());
        try {
            form.requestSubmit();if(!overlay.hidden) throw Error('Formulaire invalide');
            form.elements.valideur.value='1';form.onsubmit=()=>false;
            form.requestSubmit();if(!overlay.hidden) throw Error('Confirmation annulée');
            form.onsubmit=null;
            const guard=event=>{event.preventDefault();event.stopImmediatePropagation();};
            form.addEventListener('submit',guard,true);form.requestSubmit();
            if(!overlay.hidden) throw Error('Contrôle métier refusé');
            form.removeEventListener('submit',guard,true);
            form.requestSubmit();if(overlay.hidden) throw Error('Chargement absent pour avis CS');
            if(new FormData(form).get('valideur')!=='1') throw Error('Données perdues');
            const duplicate=new Event('submit',{bubbles:true,cancelable:true});
            form.dispatchEvent(duplicate);if(!duplicate.defaultPrevented) throw Error('Double soumission');
            window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}));
            if(!overlay.hidden) throw Error('Chargement conservé au retour');
            document.querySelector('#autre').requestSubmit();if(!overlay.hidden) throw Error('Action hors périmètre');
            result.textContent='LOADING_OK';
        } catch(error){result.textContent=error.stack;}
        </script>'''
        with tempfile.TemporaryDirectory() as temporary:
            page=Path(temporary)/'loading.html';page.write_text(html,encoding='utf-8')
            response=subprocess.run([str(CHROME),'--headless=new','--disable-gpu','--no-first-run',
                '--disable-background-networking',f'--user-data-dir={temporary}/profile',
                '--virtual-time-budget=2000','--dump-dom',page.as_uri()],capture_output=True,
                timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
            dom=response.stdout.decode('utf-8',errors='replace')
            self.assertIn('<pre id="result">LOADING_OK</pre>',dom,re.findall(r'<pre id="result">(.*?)</pre>',dom,re.S))
