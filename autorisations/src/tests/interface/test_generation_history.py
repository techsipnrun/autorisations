from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
import tempfile
from types import SimpleNamespace
from unittest import skipUnless

from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings
from django.urls import include, path

urlpatterns = [path('document-generation/', include('document_generation.urls'))]
CHROME = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')


@skipUnless(CHROME.exists(), 'Chrome absent')
@override_settings(ROOT_URLCONF=__name__)
class GenerationHistoryInterfaceTests(SimpleTestCase):
    def test_historique_et_telechargement_sans_debordement(self):
        src = Path(__file__).resolve().parents[2]
        history = render_to_string('document_generation/generation_history.html', {
            'dossier': SimpleNamespace(numero=31770683),
            'csrf_token': 'test-token',
            'generation_history': [SimpleNamespace(pk=pk, date=datetime(2026, 11, 5, tzinfo=timezone.utc),
                template_snapshot={'nom': 'Modèle original'}, user=SimpleNamespace(username='louis', get_full_name=lambda: 'Louis Test'),
                id_document=SimpleNamespace(titre='DIR-I-2026-Test_2.docx', emplacement='Test/2026/Dossier/Work/')) for pk in (5,6,7,8)],
        })
        css = (src / 'document_generation/static/document_generation/css/generation_fields.css').read_text(encoding='utf-8')
        javascript = (src / 'document_generation/static/document_generation/js/generation_history.js').read_text(encoding='utf-8')
        mock = """
        let checks=0,relinks=0,removals=0,confirmations=[],allowConfirm=true;
        window.confirm=text=>{confirmations.push(text);return allowConfirm;};
        const response=result=>new Response(JSON.stringify(result),{headers:{'Content-Type':'application/json'}});
        window.fetch=async(url,options={})=>{
            if(url.includes('/verifier/')) {checks++;return response({files:[{id:5,state:'found'},{id:6,state:'missing'},{id:7,state:'missing'},{id:8,state:'unknown'}]});}
            if(url.includes('/fichiers/')) return response({folders:[{destination:'Test/2026/Dossier/Work/',files:['Renomme.docx']}]});
            if(options.headers['X-CSRFToken']!=='test-token') throw new Error('CSRF absent');
            if(url.includes('/associer/')) {relinks++;return response({filename:'Renomme.docx',destination:'Test/2026/Dossier/Work/',message:'Fichier associé.'});}
            if(url.includes('/supprimer/')) {removals++;return response({message:'Supprimé de l’historique.'});}
            throw new Error('URL inattendue');
        };
        """
        script = """
        document.addEventListener('DOMContentLoaded',async()=>{
        const result=document.createElement('pre');result.id='result';document.body.append(result);
        const wait=async predicate=>{for(let i=0;i<80;i++){if(predicate()) return;await new Promise(resolve=>setTimeout(resolve,20));}throw new Error('Attente expirée');};
        try {
            const table=document.querySelector('.generation-history');
            if(!table.textContent.includes('Modèle original') || !table.textContent.includes('DIR-I-2026-Test_2.docx') || !table.textContent.includes('Louis Test')) throw new Error('Historique incomplet');
            if(table.querySelector('a').getAttribute('href')!=='/document-generation/dossier/31770683/generation/5/telecharger/') throw new Error('Lien incorrect');
            await wait(()=>checks===1 && table.querySelector('.is-found'));
            const missing=table.querySelector('[data-generation-id="6"]');
            if(!missing.querySelector('.is-missing') || missing.querySelector('[data-missing-actions]').hidden) throw new Error('Actions fichier manquant absentes');
            const unknown=table.querySelector('[data-generation-id="8"]');
            if(!unknown.querySelector('.is-unknown') || !unknown.querySelector('[data-missing-actions]').hidden) throw new Error('Erreur NAS traitée comme absence');
            missing.querySelector('[data-find-file]').click();
            await wait(()=>!table.querySelector('#history-file-choice').disabled);
            if(!table.querySelector('dialog').open) throw new Error('Dialogue fermé');
            const bounds=table.querySelector('dialog').getBoundingClientRect();
            if(Math.abs((bounds.left+bounds.right)/2-innerWidth/2)>2 || Math.abs((bounds.top+bounds.bottom)/2-innerHeight/2)>2) throw new Error('Dialogue non centré');
            if(!table.querySelector('dialog [type=submit]').disabled) throw new Error('Association active sans sélection');
            table.querySelector('#history-file-choice').selectedIndex=1;
            table.querySelector('#history-file-choice').dispatchEvent(new Event('change'));
            if(table.querySelector('dialog [type=submit]').disabled) throw new Error('Sélection ignorée');
            allowConfirm=false;
            table.querySelector('dialog [type=submit]').click();
            if(relinks!==0) throw new Error('Association malgré annulation');
            allowConfirm=true;
            table.querySelector('dialog [type=submit]').click();
            await wait(()=>relinks===1 && !table.querySelector('dialog').open);
            if(missing.querySelector('[data-history-filename]').textContent!=='Renomme.docx' || !missing.querySelector('.is-found')) throw new Error('Réassociation non affichée');
            table.querySelector('[data-generation-id="7"] [data-remove-history]').click();
            await wait(()=>removals===1 && !table.querySelector('[data-generation-id="7"]'));
            if(confirmations.filter(text=>text.startsWith('Associer')).length!==2 || !confirmations.some(text=>text.startsWith('Supprimer'))) throw new Error('Confirmations absentes');
            if(document.documentElement.scrollWidth>innerWidth+1) throw new Error('Débordement de page');
            result.textContent='HISTORY_OK';
        } catch(error) {result.textContent=error.stack;}
        });
        """
        with tempfile.TemporaryDirectory() as temporary:
            page = Path(temporary) / 'history.html'
            page.write_text(f'<!doctype html><meta charset="utf-8"><style>body{{margin:24px;font-family:Arial}}{css}</style>{history}<script>{mock}</script><script>{javascript}</script><script>{script}</script>', encoding='utf-8')
            for width in (540, 1600):
                with self.subTest(width=width):
                    response = subprocess.run([str(CHROME), '--headless=new', '--disable-gpu', '--no-first-run',
                        '--disable-background-networking', f'--user-data-dir={temporary}/profile-{width}',
                        f'--window-size={width},1000', '--virtual-time-budget=5000', '--dump-dom', page.as_uri()], capture_output=True,
                        timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
                    dom = response.stdout.decode('utf-8', errors='replace')
                    self.assertIn('<pre id="result">HISTORY_OK</pre>', dom,
                                  re.findall(r'<pre id="result">(.*?)</pre>', dom, re.S))
