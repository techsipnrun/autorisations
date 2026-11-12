from pathlib import Path
import re
import subprocess
import tempfile
from unittest import skipUnless

from django.test import SimpleTestCase

CHROME = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')


@skipUnless(CHROME.exists(), 'Chrome absent')
class GenerationAutosaveTests(SimpleTestCase):
    def test_restore_fields_and_isolate_dossier_template_user(self):
        root = Path(__file__).resolve().parents[2]
        script = (root / 'document_generation/static/document_generation/js/generation_autosave.js').read_text(encoding='utf-8')
        html = '''<!doctype html><meta charset="utf-8"><form id="generation-form" data-draft-key="1:2:3">
        <section class="known-information"><input name="edit_known" value="1"><button type="button" class="edit-known"></button>
        <div id="known-editor"><fieldset><input name="known-balise_1" value="Commune"></fieldset></div><div id="known-display"></div></section>
        <section class="manual-fields"><input name="balise_2" value="Nom"><input name="balise_3" type="checkbox" checked>
        <select name="balise_4" multiple><option value="a" selected>A</option><option value="b" selected>B</option></select>
        <input name="number_selection" value="reserved"><input name="output_filename" value="custom"></section></form><pre id="result"></pre>
        <script>localStorage.clear();</script>'''
        html += f'<script>{script}</script>'
        html += '''<script>
        window.saveDocumentGenerationDraft();
        const form=document.querySelector('form');
        form.elements['known-balise_1'].value='';form.elements.balise_2.value='';form.elements.balise_3.checked=false;
        [...form.elements.balise_4.options].forEach(option=>option.selected=false);
        form.elements.number_selection.value='';form.elements.output_filename.value='default';
        </script>'''
        html += f'<script>{script}</script>'
        html += '''<script>
        try {
            if(form.elements['known-balise_1'].value!=='Commune' || form.elements.balise_2.value!=='Nom'
                || !form.elements.balise_3.checked || form.elements.balise_4.selectedOptions.length!==2) throw Error('Restoration failed');
            if(form.elements.number_selection.value || form.elements.output_filename.value!=='default') throw Error('Number or filename restored');
            if(localStorage.getItem('agida:generation-draft:2:2:3') || localStorage.getItem('agida:generation-draft:1:3:3')
                || localStorage.getItem('agida:generation-draft:1:2:4')) throw Error('Scope leaked');
            document.querySelector('#result').textContent='AUTOSAVE_OK';
        } catch(error) {document.querySelector('#result').textContent=error.stack;}
        </script>'''
        with tempfile.TemporaryDirectory() as temporary:
            page = Path(temporary) / 'autosave.html'
            page.write_text(html, encoding='utf-8')
            response = subprocess.run([str(CHROME), '--headless=new', '--disable-gpu', '--no-first-run',
                '--disable-background-networking', f'--user-data-dir={temporary}/profile', '--virtual-time-budget=2000',
                '--dump-dom', page.as_uri()], capture_output=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
            dom = response.stdout.decode('utf-8', errors='replace')
            self.assertEqual(re.findall(r'<pre id="result">(.*?)</pre>', dom, re.S), ['AUTOSAVE_OK'])
