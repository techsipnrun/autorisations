from pathlib import Path
import re
import subprocess
import tempfile
from unittest import skipUnless

from django.test import SimpleTestCase

CHROME=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')


@skipUnless(CHROME.exists(),'Chrome absent')
class ActFileCandidatesTests(SimpleTestCase):
    def test_candidats_survol_et_changement_de_nature_dans_les_trois_formulaires(self):
        root=Path(__file__).resolve().parents[2]
        script=(root/'document_generation/static/document_generation/js/act_file_guard.js').read_text(encoding='utf-8')
        css=(root/'document_generation/static/document_generation/css/act_file_guard.css').read_text(encoding='utf-8')
        template=(root/'instruction/templates/instruction/instruction_dossier.html').read_text(encoding='utf-8')
        select_file=template.split('        function selectionnerFichierWorkGeneric',1)[1].split('        function selectionnerFichierRapportCA',1)[0]
        select_file='function selectionnerFichierWorkGeneric'+select_file
        forms=[]
        for index in range(3):
            items=''.join(f'''<li><button type="button" class="btn-fichier-work files-{index}" onclick="selectionnerFichierWorkGeneric(this,'{name}','work-{index}','label-{index}','.files-{index}')">{name}</button></li>'''
                for name in ('arrete.docx','arrete-v2.docx','courrier.docx','manuel.docx','sans-numero.docx'))
            forms.append(f'''<form><select name="nature_document"><option value="">Choisir une nature</option><option value="3">Arrêté</option><option value="4">Courrier</option></select>
                <div class="projet_acte_pj"><div class="selection-fichier-work"><input type="hidden" name="piece_jointe_work" id="work-{index}">
                <ul class="liste-work-files">{items}</ul><p class="fichier-selectionne">Fichier : <strong id="label-{index}">Aucun</strong></p></div></div>
                <button type="submit">Confirmer</button></form>''')
        html='''<!doctype html><meta charset="utf-8"><style>CSS
        body{font-family:Arial;margin:12px}form{max-width:100%;margin-bottom:2rem}.liste-work-files{padding:0;list-style:none}.liste-work-files button{padding:.45rem}.generated-act-selection-layout .selection-fichier-work{width:18rem;max-width:100%}</style>
        <span data-act-repair-count hidden></span><span data-act-history-guard data-status-url="/history" data-repair-url="/repair"></span>FORMS<pre id="result"></pre>
        <script>
        window.fetch=async()=>new Response(JSON.stringify({missing:0,unknown:0,blocked:false,recognized_files:[
            {filename:'arrete.docx',nature_id:3,numero:'2026-112',nature:'Arrêté directeur',description:'Arrêté généré',document_id:1},
            {filename:'arrete-v2.docx',nature_id:3,numero:'2026-113',nature:'Arrêté directeur',description:'Autre arrêté',document_id:2},
            {filename:'courrier.docx',nature_id:4,numero:'LC/42',nature:'Courrier',author:'Louis CALU',date:'16/11/2026',description:'Courrier généré',document_id:3}
        ]}),{headers:{'Content-Type':'application/json'}});
        SELECT_FILE
        </script><script>SCRIPT</script><script>
        document.addEventListener('DOMContentLoaded',async()=>{
            const wait=async condition=>{for(let i=0;i<100;i++){if(condition())return;await new Promise(r=>setTimeout(r,20));}throw Error('Attente expiree');};
            const assert=(condition,message)=>{if(!condition)throw Error(message);};
            try {
                await wait(()=>document.querySelector('[data-act-repair-count]').hidden && !document.querySelector('form fieldset').disabled);
                for(const form of document.querySelectorAll('form')) {
                    const nature=form.querySelector('select'),file=form.querySelector('[name=piece_jointe_work]'),submit=form.querySelector('[type=submit]'),info=form.querySelector('.generated-act-provenance');
                    const button=name=>[...form.querySelectorAll('.liste-work-files button')].find(item=>item.textContent.trim()===name);
                    const change=value=>{nature.value=value;nature.dispatchEvent(new Event('change',{bubbles:true}));};
                    const hover=name=>button(name).closest('li').dispatchEvent(new Event('pointerover',{bubbles:true}));
                    const leave=name=>button(name).closest('li').dispatchEvent(new PointerEvent('pointerout',{bubbles:true,relatedTarget:form}));
                    const preparation=(number,preparedNature='3')=>{
                        form.dataset.reservedPreparationNature=preparedNature;form.dataset.reservedPreparationNumber=number;
                        if(number && nature.value===preparedNature){form.dataset.manualPreparation='prepared';form.dataset.manualPreparationNumber=number;form.dataset.manualPreparationDisplay=number;}
                        else {delete form.dataset.manualPreparation;delete form.dataset.manualPreparationNumber;delete form.dataset.manualPreparationDisplay;}
                        document.dispatchEvent(new Event('manual-act-preparation-updated'));form.dispatchEvent(new Event('change'));
                    };
                    assert([...form.querySelectorAll('.liste-work-files button')].every(item=>item.disabled),'Choix actif sans nature');
                    change('3');
                    assert(!button('arrete.docx').disabled && !button('arrete-v2.docx').disabled,'Arretes compatibles bloques');
                    assert(button('courrier.docx').disabled && button('manuel.docx').disabled && button('sans-numero.docx').disabled,'Candidats incompatibles actifs');
                    button('manuel.docx').click();assert(!file.value && submit.disabled,'Word neutre selectionne sans reservation');
                    hover('manuel.docx');assert(!info.hidden && info.classList.contains('is-mismatch') && info.textContent.includes('Préparer un projet'),'Explication Word neutre absente');
                    leave('manuel.docx');assert(info.hidden,'Message persistant apres survol');
                    hover('courrier.docx');assert(info.textContent.includes('Courrier') && info.textContent.includes('Louis CALU'),'Provenance autre nature absente');
                    leave('courrier.docx');button('arrete.docx').click();await Promise.resolve();
                    assert(file.value==='arrete.docx' && !submit.disabled,'Arrete valide non selectionne');
                    change('4');await Promise.resolve();
                    assert(!file.value && submit.disabled && form.querySelector('.fichier-selectionne strong').textContent==='Aucun','Ancien choix incompatible conserve');
                    button('courrier.docx').click();await Promise.resolve();assert(file.value==='courrier.docx' && !submit.disabled,'Courrier valide refuse');
                    change('3');preparation('2026-112');
                    assert(!button('manuel.docx').disabled && !button('sans-numero.docx').disabled && !button('arrete.docx').disabled && button('arrete-v2.docx').disabled,'Reservation non appliquee aux candidats');
                    hover('arrete-v2.docx');assert(info.textContent.includes('ne porte pas le numéro réservé'),'Explication numero different absente');
                    button('arrete-v2.docx').click();assert(!file.value,'Numero incompatible selectionne');
                    leave('arrete-v2.docx');button('manuel.docx').click();await Promise.resolve();
                    assert(file.value==='manuel.docx' && !submit.disabled && info.querySelector('strong')?.textContent==='2026-112','Word manuel reserve refuse');
                    preparation('');await Promise.resolve();assert(!file.value && submit.disabled && button('manuel.docx').disabled,'Choix conserve apres annulation');
                    change('4');preparation('2026-112','3');assert(!button('courrier.docx').disabled && button('manuel.docx').disabled,'Reservation autre nature prise en compte');
                    const blocked=button('manuel.docx');assert(getComputedStyle(blocked).backgroundColor==='rgb(241, 241, 241)','Fond grise absent');
                }
                document.querySelector('#result').textContent='CANDIDATES_OK';
            }catch(error){document.querySelector('#result').textContent=error.stack;}
        });</script>'''.replace('CSS',css).replace('FORMS',''.join(forms)).replace('SELECT_FILE',select_file).replace('SCRIPT',script)
        with tempfile.TemporaryDirectory() as temporary:
            page=Path(temporary)/'candidates.html';page.write_text(html,encoding='utf-8')
            for width in (540,1600):
                with self.subTest(width=width):
                    response=subprocess.run([str(CHROME),'--headless=new','--disable-gpu','--no-first-run','--disable-background-networking',
                        f'--user-data-dir={temporary}/profile-{width}',f'--window-size={width},1000','--virtual-time-budget=8000','--dump-dom',page.as_uri()],
                        capture_output=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
                    dom=response.stdout.decode('utf-8',errors='replace')
                    self.assertEqual(re.findall(r'<pre id="result">(.*?)</pre>',dom,re.S),['CANDIDATES_OK'])
