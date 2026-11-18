import base64
from io import BytesIO
from pathlib import Path
import re
import subprocess
import tempfile
from unittest import skipUnless

from django.test import SimpleTestCase
from docx import Document
from document_generation.services.docx_renderer import DocxRenderer


CHROME = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')


@skipUnless(CHROME.exists(), 'Chrome absent')
class DocxPreviewTests(SimpleTestCase):
    def test_rendu_reel_docx_et_echec_conserve_apercu(self):
        root = Path(__file__).resolve().parents[2] / 'document_generation/static/document_generation'
        document = Document()
        document.add_paragraph('Projet de test DOCX {{ projet.nom }}')
        document.add_paragraph('{% if projet.commune %}Commune renseignée{% else %}Commune absente{% endif %}')
        document.add_paragraph('{% for nom in projet.beneficiaires %}{{ nom }}{% endfor %}')
        from docx.enum.style import WD_STYLE_TYPE
        from docx.shared import Pt
        document.styles['Normal'].paragraph_format.space_after = Pt(10)
        from docx.oxml.ns import qn
        for spacing in document.styles.element.xpath('./w:docDefaults/w:pPrDefault/w:pPr/w:spacing'):
            spacing.set(qn('w:after'), '0')
        document.styles.add_style('StandardSansHeritage', WD_STYLE_TYPE.PARAGRAPH)
        document.add_paragraph('{%p if projet.commune %}')
        document.add_paragraph('Vu sans espacement herite', style='StandardSansHeritage')
        document.add_paragraph('{%p endif %}')
        explicit = document.add_paragraph('Espacement volontaire', style='StandardSansHeritage')
        explicit.paragraph_format.space_after = Pt(18)
        document.add_page_break()
        document.add_paragraph('Deuxieme page')
        document.add_page_break()
        document.add_paragraph('Troisieme page')
        buffer = BytesIO()
        document.save(buffer)
        with DocxRenderer().render_to_memory(buffer.getvalue(), {'projet': {'nom': 'Alice', 'commune': 'Saint-Denis', 'beneficiaires': ['Alice']}}) as rendered:
            encoded = base64.b64encode(rendered.getvalue()).decode()
        with DocxRenderer().render_to_memory(buffer.getvalue(), {'projet': {'nom': None, 'commune': None, 'beneficiaires': []}},
                missing_markers=[{'code': 'projet.nom', 'label': 'Nom'}, {'code': 'projet.commune', 'label': 'Commune'},
                                 {'code': 'projet.beneficiaires', 'label': 'Liste des bénéficiaires'}]) as rendered:
            marked_encoded = base64.b64encode(rendered.getvalue()).decode()
        scripts = '\n'.join((root / name).read_text(encoding='utf-8') for name in (
            'vendor/jszip-3.10.2.min.js', 'vendor/docx-preview-0.4.1.min.js',
            'vendor/html2canvas-1.4.1.min.js', 'vendor/jspdf-4.2.1.min.js'))
        app = (root / 'js/docx_preview.js').read_text(encoding='utf-8')
        css = (root / 'css/generation_fields.css').read_text(encoding='utf-8')
        html = '''<!doctype html><meta charset="utf-8"><body>
        <form id="generation-form" data-generation-valid="false"><input name="balise_1" value="">
        <button name="action" value="generate_file">Générer</button><button name="action" value="preview_pdf">PDF</button></form>
        <iframe id="pdf" title="PDF"></iframe>
        <aside data-docx-preview>
        <p data-docx-preview-status></p><p data-docx-preview-error hidden></p><div class="docx-preview-viewport"><div data-docx-preview-content></div><div data-docx-preview-loading hidden>Chargement local</div></div><div data-docx-preview-missing hidden><ul></ul></div></aside>
        <dialog data-generation-progress>Chargement</dialog><pre id="result"></pre>
        '''
        setup = '''
        let requests=0,fail=false,aborts=0;
        let exportedPages=0,exportedBytes=0,paintedPages=0;
        const PDF=window.jspdf.jsPDF;
        window.jspdf.jsPDF=function(options){
            const pdf=new PDF(options);
            pdf.save=()=>{exportedPages=pdf.getNumberOfPages();exportedBytes=pdf.output('arraybuffer').byteLength;};
            return pdf;
        };
        const capture=window.html2canvas;
        window.html2canvas=async(...args)=>{
            const canvas=await capture(...args),data=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
            for(let i=0;i<data.length;i+=16) if(data[i+3]>0 && data[i]<200){paintedPages++;break;}
            return canvas;
        };
        window.showDocumentGenerationLoading=()=>document.querySelector('dialog').showModal();
        window.fetch=async(url,options)=>{
            requests++;
            const expected=document.querySelector('form').getAttribute('action') || location.href;
            if(url!==expected || String(url).includes('RadioNodeList')) throw new Error('URL incorrecte: '+url);
            if(document.querySelector('[data-docx-preview-loading]').hidden || document.querySelector('dialog').open) throw new Error('Chargement local absent');
            if(options.body.get('action')!=='preview_docx') throw new Error('Saisies non transmises');
            if(requests===4) await new Promise((resolve,reject)=>{
                const timer=setTimeout(resolve,2500);
                options.signal.addEventListener('abort',()=>{clearTimeout(timer);aborts++;reject(new DOMException('Annule','AbortError'));},{once:true});
            });
            if(fail) return new Response(JSON.stringify({error:'Erreur de test'}),{status:400,headers:{'Content-Type':'application/json'}});
            return new Response(JSON.stringify({docx:options.body.get('balise_1') ? 'ENCODED' : 'MARKED_DOCUMENT',missing:options.body.get('balise_1') ? [] : [{code:'projet.nom',label:'Nom',reason:'A renseigner'}]}),{headers:{'Content-Type':'application/json'}});
        };
        '''.replace('ENCODED', encoded).replace('MARKED_DOCUMENT', marked_encoded)
        scenario = '''
        (async()=>{
            const result=document.getElementById('result');
            const wait=async predicate=>{for(let i=0;i<500;i++){if(predicate())return;await new Promise(resolve=>setTimeout(resolve,20));}throw new Error('Attente expiree');};
            try {
                const form=document.querySelector('form'),content=document.querySelector('[data-docx-preview-content]');
                const input=form.querySelector('[name=balise_1]');
                await wait(()=>requests===1 && document.querySelector('[data-docx-preview-loading]').hidden);
                const missingBox=document.querySelector('[data-docx-preview-missing]');
                if(missingBox.hidden || missingBox.querySelector('li').textContent!=='Nom' || missingBox.querySelector('code')) throw new Error('Liste des balises incorrecte');
                const initialFrame=content.querySelector('iframe');
                const marker=[...initialFrame.contentDocument.querySelectorAll('span')].find(span=>span.textContent==='Nom');
                if(!marker || initialFrame.contentWindow.getComputedStyle(marker).color!=='rgb(180, 35, 24)') throw new Error('Repere rouge absent dans le rendu Word');
                if(Number(initialFrame.contentWindow.getComputedStyle(marker).fontWeight)<700) throw new Error('Nom de balise non gras');
                const instruction=[...initialFrame.contentDocument.querySelectorAll('span')].find(span=>span.textContent===' à renseigner]');
                if(!instruction || Number(initialFrame.contentWindow.getComputedStyle(instruction).fontWeight)>=700) throw new Error('Instruction en gras');
                for(const expected of ['Commune', 'Liste des bénéficiaires']) {
                    const blockMarker=[...initialFrame.contentDocument.querySelectorAll('span')].find(span=>span.textContent===expected);
                    if(!blockMarker || initialFrame.contentWindow.getComputedStyle(blockMarker).color!=='rgb(180, 35, 24)') throw new Error('Repere de bloc absent: '+expected);
                    if(Number(initialFrame.contentWindow.getComputedStyle(blockMarker).fontWeight)<700) throw new Error('Nom de champ de bloc non gras');
                }
                if(!document.querySelector('[data-docx-preview]').classList.contains('has-missing-values')) throw new Error('Bordure orange absente');
                for(const value of ['S','Sa','Saisie courante']) {input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));}
                await wait(()=>requests===2 && document.querySelector('[data-docx-preview-loading]').hidden);
                if(!document.querySelector('[data-docx-preview-missing]').hidden) throw new Error('Balise complete encore listee');
                if(document.querySelector('[data-docx-preview]').classList.contains('has-missing-values')) throw new Error('Bordure orange conservee');
                input.dispatchEvent(new Event('input',{bubbles:true}));
                await new Promise(resolve=>setTimeout(resolve,800));
                if(requests!==2) throw new Error('Requete dupliquee sans changement');
                const frame=content.querySelector('iframe');
                if(!frame?.contentDocument.body.textContent.includes('Projet de test DOCX')) throw new Error('Rendu DOCX absent: '+document.querySelector('[data-docx-preview-error]').textContent);
                if(frame.getAttribute('sandbox')!=='allow-same-origin allow-modals') throw new Error('Isolation absente');
                const paragraphs=[...frame.contentDocument.querySelectorAll('p')];
                const compact=paragraphs.find(p=>p.textContent==='Vu sans espacement herite');
                const spaced=paragraphs.find(p=>p.textContent==='Espacement volontaire');
                if(!compact || parseFloat(frame.contentWindow.getComputedStyle(compact).marginBottom)>0.1) throw new Error('Espacement Normal applique au style sans heritage');
                if(!spaced || parseFloat(frame.contentWindow.getComputedStyle(spaced).marginBottom)<20) throw new Error('Espacement volontaire perdu');
                if(!document.getElementById('pdf')) throw new Error('PDF perdu');
                const toolbar=document.querySelector('.docx-preview-toolbar'),pageInput=toolbar.querySelector('[data-docx-page]');
                if(getComputedStyle(toolbar).backgroundColor!=='rgb(56, 58, 57)') throw new Error('Style sombre absent');
                if(document.documentElement.scrollWidth>innerWidth) throw new Error('Debordement de la barre');
                if(toolbar.hidden || toolbar.querySelector('[data-docx-total]').textContent!=='/ 3') throw new Error('Compteur incorrect');
                if(!toolbar.querySelector('[data-docx-previous]').disabled) throw new Error('Precedent actif sur premiere page');
                toolbar.querySelector('[data-docx-next]').click();
                if(pageInput.value!=='2') throw new Error('Navigation page suivante incorrecte: '+pageInput.value);
                const zoom=()=>parseInt(toolbar.querySelector('[data-docx-zoom]').value);
                const initialZoom=zoom();toolbar.querySelector('[data-docx-plus]').click();
                if(zoom()<=initialZoom || pageInput.value!=='2') throw new Error('Zoom ou conservation de page incorrect');
                toolbar.querySelector('[data-docx-minus]').click();
                if(zoom()!==initialZoom) throw new Error('Dezoom incorrect');
                pageInput.value='99';pageInput.dispatchEvent(new Event('change'));
                if(pageInput.value!=='3' || !toolbar.querySelector('[data-docx-next]').disabled) throw new Error('Limite derniere page incorrecte');
                frame.contentWindow.scrollTo(0,0);frame.contentWindow.dispatchEvent(new Event('scroll'));
                if(pageInput.value!=='1') throw new Error('Compteur non synchronise au scroll');
                toolbar.querySelector('[data-docx-fit]').click();
                if(toolbar.querySelector('[data-docx-fit]').getAttribute('aria-pressed')!=='true') throw new Error('Ajustement absent');
                const options=toolbar.querySelector('.docx-options-menu'),optionsButton=toolbar.querySelector('[data-docx-options]');
                if(!options.hidden) throw new Error('Options visibles par defaut');
                optionsButton.click();
                if(options.hidden || optionsButton.getAttribute('aria-expanded')!=='true') throw new Error('Menu ferme');
                if(options.querySelectorAll('button').length!==3) throw new Error('Options incorrectes');
                toolbar.querySelector('[data-docx-fit-page]').click();
                if(!options.hidden || toolbar.querySelector('[data-docx-fit-page]').getAttribute('aria-pressed')!=='true') throw new Error('Ajustement page absent');
                const firstSheet=frame.contentDocument.querySelector('.docx-view-sheet');
                const firstPage=firstSheet.querySelector('section');
                if(frame.contentWindow.getComputedStyle(firstPage).backgroundColor!=='rgb(255, 255, 255)') throw new Error('Page non blanche');
                const rect=firstSheet.getBoundingClientRect(),viewport=frame.contentDocument.documentElement.clientWidth;
                if(Math.abs(rect.left+rect.width/2-viewport/2)>3) throw new Error('Page non centree: '+rect.left+' / '+rect.width+' / '+viewport);
                const manualZoom=toolbar.querySelector('[data-docx-zoom]');
                manualZoom.value='125';manualZoom.dispatchEvent(new Event('change'));
                if(zoom()!==125) throw new Error('Zoom manuel ignore');
                manualZoom.value='500';manualZoom.dispatchEvent(new Event('change'));
                if(zoom()!==200) throw new Error('Zoom maximal non borne');
                manualZoom.value='abc';manualZoom.dispatchEvent(new Event('change'));
                if(zoom()!==200) throw new Error('Zoom invalide accepte');
                toolbar.querySelector('[data-docx-fit-page]').click();
                const initialWidth=firstSheet.style.width,initialHeight=firstSheet.style.height;
                toolbar.querySelector('[data-docx-rotate]').click();
                if(firstSheet.style.width!==initialHeight || firstSheet.style.height!==initialWidth) throw new Error('Rotation sans dimensions adaptees');
                for(let i=0;i<3;i++) toolbar.querySelector('[data-docx-rotate]').click();
                if(firstSheet.style.width!==initialWidth || firstSheet.querySelector('section').style.transform.indexOf('rotate(0deg)')<0) throw new Error('Rotation complete incorrecte');
                let prints=0;frame.contentWindow.print=()=>prints++;
                toolbar.querySelector('[data-docx-print]').click();
                if(prints!==1) throw new Error('Impression absente');
                const printRules=[...frame.contentDocument.styleSheets].flatMap(sheet=>[...sheet.cssRules]);
                if(!printRules.some(rule=>rule.type===CSSRule.PAGE_RULE && rule.style.margin==='0px')) throw new Error('Marges navigateur conservees');
                optionsButton.click();toolbar.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
                if(!options.hidden || document.activeElement!==optionsButton) throw new Error('Fermeture clavier absente');
                const twoPages=toolbar.querySelector('[data-docx-two-pages]');
                twoPages.click();
                const sheets=[...frame.contentDocument.querySelectorAll('.docx-view-sheet')];
                const first=sheets[0].getBoundingClientRect(),second=sheets[1].getBoundingClientRect(),third=sheets[2].getBoundingClientRect();
                if(twoPages.getAttribute('aria-pressed')!=='true' || Math.abs(first.top-second.top)>1 || second.left<=first.left || third.top<=first.top) throw new Error('Disposition deux pages incorrecte');
                twoPages.click();
                if(twoPages.getAttribute('aria-pressed')!=='false' || sheets[1].getBoundingClientRect().top<=sheets[0].getBoundingClientRect().top) throw new Error('Retour une page incorrect');
                const download=toolbar.querySelector('[data-docx-download]');
                if(download.disabled || download.nextElementSibling!==toolbar.querySelector('[data-docx-print]')) throw new Error('Telechargement PDF incorrect');
                twoPages.click();toolbar.querySelector('[data-docx-rotate]').click();
                manualZoom.value='86';manualZoom.dispatchEvent(new Event('change'));
                download.click();
                await wait(()=>!download.disabled);
                if(exportedPages!==3 || exportedBytes<1000 || paintedPages!==3) throw new Error('Export PDF absent ou vide: '+exportedPages+' / '+exportedBytes+' / '+paintedPages+' / '+document.querySelector('[data-docx-preview-error]').textContent);
                if(requests!==2) throw new Error('Export avec requete serveur');
                if(zoom()!==86 || twoPages.getAttribute('aria-pressed')!=='true' || firstSheet.querySelector('section').style.transform.indexOf('rotate(270deg)')<0) throw new Error('Export modifie la consultation');
                document.querySelector('form').setAttribute('action','/document-generation/dossier/31770683/?demarche=14&template=1');
                fail=true;input.value='Nouvelle saisie';input.dispatchEvent(new Event('input',{bubbles:true}));await wait(()=>requests===3 && document.querySelector('[data-docx-preview-loading]').hidden);
                if(content.querySelector('iframe')!==frame) throw new Error('Ancien rendu perdu');
                if(toolbar.hidden || toolbar.querySelector('[data-docx-total]').textContent!=='/ 3') throw new Error('Navigation perdue apres erreur');
                if(document.querySelector('[data-docx-preview-error]').textContent!=='Erreur de test') throw new Error('Erreur non affichee');
                if(form.getAttribute('aria-busy')==='true' || document.body.style.overflow==='hidden' || document.querySelector('dialog').open) throw new Error('Interface bloquee');
                fail=false;input.value='Ancienne saisie';input.dispatchEvent(new Event('input',{bubbles:true}));
                await wait(()=>requests===4);
                input.value='Derniere saisie';input.dispatchEvent(new Event('input',{bubbles:true}));
                await wait(()=>requests===5 && document.querySelector('[data-docx-preview-loading]').hidden);
                if(aborts!==1 || !document.querySelector('[data-docx-preview-error]').hidden || content.querySelector('iframe')===frame) throw new Error('Annulation ou remplacement incorrect');
                await new Promise(resolve=>setTimeout(resolve,800));
                if(requests!==5) throw new Error('Actualisation en boucle');
                result.textContent='DOCX_OK';
            } catch(error) { result.textContent=error.stack; }
        })();
        '''
        html += f'<style>{css}</style><script>{scripts}</script><script>{setup}</script><script>{app}</script><script>{scenario}</script></body>'
        with tempfile.TemporaryDirectory() as temporary:
            page = Path(temporary) / 'preview.html'
            page.write_text(html, encoding='utf-8')
            for width in (540, 1200):
                with self.subTest(width=width):
                    response = subprocess.run([str(CHROME), '--headless=new', '--disable-gpu', '--no-first-run',
                        '--disable-background-networking', f'--user-data-dir={temporary}/profile-{width}',
                        f'--window-size={width},1000', '--virtual-time-budget=20000', '--dump-dom', page.as_uri()], capture_output=True,
                        timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
                    dom = response.stdout.decode('utf-8', errors='replace')
                    self.assertEqual(re.findall(r'<pre id="result">(.*?)</pre>', dom, re.S), ['DOCX_OK'])
