import base64
from io import BytesIO
from pathlib import Path
import re
import subprocess
import tempfile
from unittest import skipUnless

from django.test import SimpleTestCase
from docx import Document

CHROME=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')


@skipUnless(CHROME.exists(),'Chrome absent')
class DocumentHoverWordTests(SimpleTestCase):
    def test_vrai_word_charge_a_la_demande_et_reutilise(self):
        root=Path(__file__).resolve().parents[2]
        vendor=root/'document_generation/static/document_generation/vendor'
        script=(root/'instruction/static/instruction/js/document_hover_preview.js').read_text(encoding='utf-8')
        document=Document();document.add_heading('Projet de test',level=1)
        document.add_paragraph('Reference TEST/LC/JPD')
        document.add_table(rows=1,cols=1).cell(0,0).text='Texte dans un tableau'
        stream=BytesIO();document.save(stream)
        encoded=base64.b64encode(stream.getvalue()).decode()
        html=f'''<!doctype html><html><head><meta charset="utf-8">
        <style>.document-apercu-popover{{display:none;position:fixed;width:min(520px,90vw);height:480px}}.is-preview-open .document-apercu-popover{{display:block}}.document-apercu-contenu{{width:100%;height:100%;border:0}}</style>
        </head><body>
        <span class="document-avec-apercu"><button class="document-apercu-trigger" data-preview-type="docx" data-preview-url="/test.docx">Apercu</button>
        <span class="document-apercu-pont"></span><span class="document-apercu-popover">Chargement</span></span><pre id="result"></pre>
        <script>let requests=0;window.fetch=async()=>{{requests++;return new Response(Uint8Array.from(atob('{encoded}'),c=>c.charCodeAt(0)));}};</script>
        <script data-jszip-url="{(vendor/'jszip-3.10.2.min.js').as_uri()}" data-docx-url="{(vendor/'docx-preview-0.4.1.min.js').as_uri()}">{script}</script><script>
        document.addEventListener('DOMContentLoaded',async()=>{{
            const wait=async predicate=>{{for(let i=0;i<200;i++){{if(predicate())return;await new Promise(r=>setTimeout(r,20));}}throw Error('Timeout rendu Word');}};
            try {{
                if(requests || window.docx || window.JSZip)throw Error('Chargement anticipe');
                const trigger=document.querySelector('button');trigger.click();
                await wait(()=>document.querySelector('iframe')?.contentDocument?.body.textContent.includes('Texte dans un tableau'));
                const frame=document.querySelector('iframe'),doc=frame.contentDocument;
                if(!doc.body.textContent.includes('Reference TEST/LC/JPD') || !doc.querySelector('section.docx'))throw Error('Word incomplet');
                if(doc.querySelector('.notice'))throw Error('Avertissement encore present');
                if(frame.getAttribute('sandbox')!=='allow-same-origin')throw Error('Rendu non isole');
                await wait(()=>Number(doc.querySelector('#word').style.zoom)>0);
                if(Number(doc.querySelector('#word').style.zoom)>1)throw Error('Page agrandie');
                trigger.click();trigger.click();await new Promise(r=>setTimeout(r,100));
                if(requests!==1)throw Error('Word recharge inutilement');
                document.querySelector('#result').textContent='WORD_HOVER_OK';
            }}catch(error){{document.querySelector('#result').textContent=error.stack;}}
        }});</script></body></html>'''
        with tempfile.TemporaryDirectory() as temporary:
            page=Path(temporary)/'word.html';page.write_text(html,encoding='utf-8')
            for width in (540,1600):
                with self.subTest(width=width):
                    response=subprocess.run([str(CHROME),'--headless=new','--disable-gpu','--no-first-run',
                        '--disable-background-networking',f'--user-data-dir={temporary}/profile-{width}',
                        f'--window-size={width},900','--virtual-time-budget=8000','--dump-dom',page.as_uri()],
                        capture_output=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
                    dom=response.stdout.decode('utf-8',errors='replace')
                    self.assertEqual(re.findall(r'<pre id="result">(.*?)</pre>',dom,re.S),['WORD_HOVER_OK'])
