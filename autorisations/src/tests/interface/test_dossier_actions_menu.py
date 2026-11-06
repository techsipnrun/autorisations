from pathlib import Path
import re
import subprocess
import tempfile
from types import SimpleNamespace
from unittest import skipUnless

from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings
from django.urls import include, path


CHROME = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
urlpatterns = [path('document-generation/', include('document_generation.urls')), path('', include('autorisations.urls'))]


@skipUnless(CHROME.exists(), 'Chrome absent')
@override_settings(ROOT_URLCONF=__name__)
class DossierActionsMenuTests(SimpleTestCase):
    def test_actions_ordonnees_et_titre_a_gauche_du_menu(self):
        src = Path(__file__).resolve().parents[2]
        context = {
            'request': SimpleNamespace(path='/instruction/31770683/', user=SimpleNamespace(is_authenticated=True, is_superuser=True)),
            'dossier': SimpleNamespace(pk=1, id=1, numero=31770683, id_demarche=SimpleNamespace(type='Démarche de test')),
            'peut_lier_dossiers': True, 'generation_documents_dev': True, 'chemin_complet': '//nas/dev/Test/',
        }
        header = render_to_string('instruction/refacto/dossier_header.html', context)
        scenario = """
        const menu=document.querySelector('.dossier-actions-menu');
        const actions=[...menu.querySelectorAll('.btn-copy-dossier,.btn-notifier-agents,.dossier-action-generer')];
        const labels=actions.map(button=>button.querySelector('span:not(.copy-feedback)')?.textContent);
        const result=document.createElement('pre');result.id='result';document.body.append(result);
        try {
            if(labels.join(',')!=='Copier,Notifier,Lier,Générer') throw new Error('Ordre incorrect');
            const positions=actions.map(button=>button.getBoundingClientRect());
            if(positions.some((rect,index)=>index && rect.top<positions[index-1].bottom)) throw new Error('Actions non verticales');
            const h1=document.querySelector('h1').getBoundingClientRect(), bounds=menu.getBoundingClientRect();
            if(h1.right>bounds.left || h1.top>=bounds.bottom) throw new Error('Titre sous le menu');
            if(document.documentElement.scrollWidth>innerWidth+1) throw new Error('Débordement');
            result.textContent='ACTIONS_OK';
        } catch(error) {result.textContent=error.stack;}
        """
        with tempfile.TemporaryDirectory() as temporary:
            for mode in ('instruction_dossier', 'preinstruction_dossier'):
                css = '\n'.join((src / f'instruction/static/instruction/css/{name}.css').read_text(encoding='utf-8')
                                for name in ('dossier', mode, 'dossiers_lies', 'dossier_actions_menu'))
                page = Path(temporary) / f'{mode}.html'
                page.write_text(f'<!doctype html><meta charset="utf-8"><style>body{{margin:16px}}{css}</style>'
                                f'<div class="formulaire">{header}</div><script>{scenario}</script>', encoding='utf-8')
                for width in (540, 1600):
                    with self.subTest(mode=mode, width=width):
                        response = subprocess.run([str(CHROME), '--headless=new', '--disable-gpu', '--no-first-run',
                            '--disable-background-networking', f'--user-data-dir={temporary}/profile-{mode}-{width}',
                            f'--window-size={width},1000', '--dump-dom', page.as_uri()], capture_output=True,
                            timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
                        dom = response.stdout.decode('utf-8', errors='replace')
                        self.assertIn('<pre id="result">ACTIONS_OK</pre>', dom,
                                      re.findall(r'<pre id="result">(.*?)</pre>', dom, re.S))
