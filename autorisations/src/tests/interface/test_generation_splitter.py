from pathlib import Path
import re
import subprocess
import tempfile
from unittest import skipUnless
from django.test import SimpleTestCase

CHROME=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')


@skipUnless(CHROME.exists(), 'Chrome absent')
class GenerationSplitterTests(SimpleTestCase):
    def test_drag_limits_keyboard_and_mobile(self):
        root=Path(__file__).resolve().parents[2]/'document_generation/static/document_generation'
        css=(root/'css/generation_fields.css').read_text(encoding='utf-8')
        script=(root/'js/generation_splitter.js').read_text(encoding='utf-8')
        html='''<!doctype html><meta charset="utf-8"><style>body{margin:20px}.generation-workspace{display:grid;gap:24px}.generation-workspace>div,.docx-preview-panel{min-width:0;height:200px}'''+css+'''</style>
        <div class="generation-workspace"><div>Formulaire</div><aside class="docx-preview-panel">Apercu</aside></div><pre id="result"></pre>
        <script>'''+script+'''</script><script>
        try {
            const workspace=document.querySelector('.generation-workspace'),handle=document.querySelector('.generation-splitter');
            const left=workspace.firstElementChild,right=workspace.querySelector('aside');
            if(innerWidth<=1100) {
                if(getComputedStyle(handle).display!=='none' || right.getBoundingClientRect().top<left.getBoundingClientRect().bottom) throw Error('Mobile layout');
            } else {
                handle.dispatchEvent(new KeyboardEvent('keydown',{key:'End',bubbles:true}));
                const available=workspace.clientWidth-24;
                if(Math.abs(left.getBoundingClientRect().width/available-.75)>.01) throw Error('Keyboard width');
                handle.setPointerCapture=()=>{};
                handle.dispatchEvent(new PointerEvent('pointerdown',{button:0,pointerId:1,clientX:0}));
                if(handle.getAttribute('aria-valuenow')!=='25') throw Error('Lower drag limit');
                handle.dispatchEvent(new PointerEvent('pointermove',{pointerId:1,clientX:innerWidth+100}));
                if(handle.getAttribute('aria-valuenow')!=='75') throw Error('Upper drag limit');
                handle.dispatchEvent(new PointerEvent('pointerup',{pointerId:1}));
                if(workspace.classList.contains('is-resizing')) throw Error('Drag not ended');
                handle.dispatchEvent(new MouseEvent('dblclick'));
                if(handle.getAttribute('aria-valuenow')!=='50') throw Error('Reset');
            }
            if(document.documentElement.scrollWidth>innerWidth) throw Error('Overflow');
            document.querySelector('#result').textContent='SPLITTER_OK';
        } catch(error) {document.querySelector('#result').textContent=error.stack;}
        </script>'''
        with tempfile.TemporaryDirectory() as temporary:
            page=Path(temporary)/'splitter.html';page.write_text(html,encoding='utf-8')
            for width in (540,1600):
                result=subprocess.run([str(CHROME),'--headless=new','--disable-gpu','--no-first-run','--disable-background-networking',
                    f'--window-size={width},1000',f'--user-data-dir={temporary}/profile-{width}',
                    '--virtual-time-budget=1000','--dump-dom',page.as_uri()],capture_output=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
                dom=result.stdout.decode('utf-8',errors='replace')
                self.assertEqual(re.findall(r'<pre id="result">(.*?)</pre>',dom,re.S),['SPLITTER_OK'])
