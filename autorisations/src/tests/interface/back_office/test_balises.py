from pathlib import Path
import subprocess
import tempfile
import re
from unittest import skipUnless
from django.template.loader import render_to_string
from django.test import SimpleTestCase

CHROME = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')


@skipUnless(CHROME.exists(), 'Chrome absent')
class BalisesInterfaceTests(SimpleTestCase):
    def test_creer_une_balise_formulaire_depuis_un_code_inconnu(self):
        src=Path(__file__).resolve().parents[3]
        body=render_to_string('backoffice/back_office_balises.html',{'csrf_token':'test-token'})
        css=(src/'backoffice/static/backoffice/css/back_office_documents.css').read_text(encoding='utf-8')
        js=(src/'backoffice/static/backoffice/js/back_office_balises.js').read_text(encoding='utf-8')
        mock="""
        history.replaceState(null,'','#documents/balises/nouvelle?code=projet.commune&template=1');
        let saved=null, reads=0;
        const payload={balises:[{id:43,code:'projet.inactive',libelle:'Balise inactive',actif:false,erreurs:[],mode:'A_RENSEIGNER'}],proprietes:[{code:'dossier.numero',nom:'Numéro du dossier'}],
            types:[{code:'TEXT',nom:'Texte'},{code:'INTEGER',nom:'Entier'},{code:'LIST',nom:'Liste répétable (texte)'}],demarches:[{id:14,nom:'Test'},{id:99,nom:'Autre'}],
            templates:[{id:1,nom:'Template Test',demarche_ids:[14],balise_codes:['projet.commune']},
                {id:2,nom:'Template global',demarche_ids:[],balise_codes:['projet.inactive']},
                {id:3,nom:'Template autre',demarche_ids:[99],balise_codes:[]}]};
        const response=data=>new Response(JSON.stringify(data),{headers:{'Content-Type':'application/json'}});
        window.fetch=async(url,options={})=>{
            if(url.includes('/champs/14/')) return response({champs:[{id:7,nom:'Commune',type:'Texte'}]});
            if(options.method==='POST') {
                if(options.body.get('csrfmiddlewaretoken')!=='test-token') throw new Error('CSRF absent');
                const sources=JSON.parse(options.body.get('sources'));
                if(sources.length!==1 || sources[0].id_demarche!=='14' || sources[0].id_champ!=='7') throw new Error('Source perdue');
                saved={id:42,code:options.body.get('code'),libelle:options.body.get('libelle'),source:options.body.get('source'),
                    source_propriete:'',mode:'CONNUE',type:options.body.get('type'),required:true,allow_blank:false,help_text:'',actif:true,
                    sources:[{id_demarche:14,id_champ:7,demarche:'Test',champ:'Commune'}],erreurs:[]};
                payload.balises=[saved];return response({balise:saved,warnings:[]});
            }
            reads++;return response(payload);
        };
        """
        scenario="""
        document.addEventListener('DOMContentLoaded',async()=>{
            const result=document.createElement('pre');result.id='result';document.body.append(result);
            const wait=async predicate=>{for(let i=0;i<70;i++){if(predicate())return;await new Promise(r=>setTimeout(r,20));}throw new Error('Attente expirée');};
            try {
                const panel=document.querySelector('[data-panel="balises"]');panel.hidden=false;
                await wait(()=>reads===1 && !document.querySelector('[data-balise-detail]').hidden);
                const form=document.querySelector('[data-balise-form]');
                if(form.elements.code.value!=='projet.commune') throw new Error('Code inconnu non prérempli');
                form.elements.libelle.value='Commune du projet';
                form.elements.source.value='FORMULAIRE';form.elements.source.dispatchEvent(new Event('change'));
                if(document.querySelector('[data-balise-mappings]').hidden) throw new Error('Sources masquées');
                document.querySelector('[data-balise-add-source]').click();
                const demarche=document.querySelector('[data-source-demarche]');demarche.value='14';demarche.dispatchEvent(new Event('change'));
                await wait(()=>document.querySelector('[data-source-champ] option[value="7"]'));
                document.querySelector('[data-source-champ]').value='7';form.elements.required.checked=true;
                if(form.elements.allow_blank) throw new Error('Ancien réglage vide encore présent');
                form.querySelector('[type="submit"]').click();
                await wait(()=>document.querySelector('[data-balise-save-status]').textContent.includes('Balise enregistrée'));
                if(!saved || saved.source!=='FORMULAIRE' || !form.elements.code.disabled) throw new Error('Enregistrement incorrect');
                if(!location.hash.startsWith('#documents/balises/42')) throw new Error('URL non mémorisée');
                if(document.querySelector('[data-balise-back]').textContent!=='← Revenir au template') throw new Error('Retour template perdu');
                await wait(()=>document.querySelector('[data-source-champ]')?.value==='7');
                form.elements.type.value='LIST';form.elements.type.dispatchEvent(new Event('change'));
                if(form.elements.source.value!=='MANUELLE' || document.querySelector('[data-balise-item-label]').hidden) throw new Error('Configuration de liste indisponible');
                form.elements.libelle_element.value='Nom';
                if(!form.elements.libelle_element.required) throw new Error('Libellé de ligne non obligatoire');
                document.querySelector('[data-balise-back]').click();
                if(location.hash!=='#documents/templates/1') throw new Error('Retour vers le mauvais écran');
                location.hash='documents/balises';
                await wait(()=>!document.querySelector('[data-balises-list]').hidden);
                if(!document.querySelector('[data-balises-list]').textContent.includes('Commune du projet')) throw new Error('Catalogue non actualisé');
                const filter=document.querySelector('[data-balises-state]');
                filter.value='inactif';filter.dispatchEvent(new Event('change'));
                if(document.querySelectorAll('[data-balises-list] button').length!==1 || !document.querySelector('[data-balises-list]').textContent.includes('Balise inactive')) throw new Error('Filtre inactif incorrect');
                filter.value='actif';filter.dispatchEvent(new Event('change'));
                if(document.querySelectorAll('[data-balises-list] button').length!==1 || !document.querySelector('[data-balises-list]').textContent.includes('Commune du projet')) throw new Error('Filtre actif incorrect');
                const sourceFilter=document.querySelector('[data-balises-source]');
                const demarcheFilter=document.querySelector('[data-balises-demarche]');
                sourceFilter.value='FORMULAIRE';sourceFilter.dispatchEvent(new Event('change'));
                if(document.querySelector('[data-balises-demarche-label]').hidden) throw new Error('Filtre démarche masqué');
                demarcheFilter.value='14';demarcheFilter.dispatchEvent(new Event('change'));
                if(document.querySelectorAll('[data-balises-list] button').length!==1) throw new Error('Source formulaire perdue');
                const templateFilter=document.querySelector('[data-balises-template]');
                if(document.querySelector('[data-balises-template-label]').hidden || templateFilter.options.length!==3) throw new Error('Choix templates incorrects');
                if([...templateFilter.options].some(option=>option.value==='3')) throw new Error('Template autre démarche proposé');
                templateFilter.value='2';templateFilter.dispatchEvent(new Event('change'));
                if(document.querySelectorAll('[data-balises-list] button').length!==0) throw new Error('Filtre template global incorrect');
                templateFilter.value='1';templateFilter.dispatchEvent(new Event('change'));
                if(document.querySelectorAll('[data-balises-list] button').length!==1) throw new Error('Filtre template associé incorrect');
                demarcheFilter.value='99';demarcheFilter.dispatchEvent(new Event('change'));
                if(document.querySelectorAll('[data-balises-list] button').length!==0) throw new Error('Démarche sans source non filtrée');
                sourceFilter.value='AGIDA';sourceFilter.dispatchEvent(new Event('change'));
                if(document.querySelector('[data-balises-demarche-label]').hidden || demarcheFilter.value!=='99') throw new Error('Filtre démarche indépendant perdu');
                if(document.querySelectorAll('[data-balises-list] button').length!==0) throw new Error('Filtre AGIDA incorrect');
                filter.value='';filter.dispatchEvent(new Event('change'));
                sourceFilter.value='MANUELLE';sourceFilter.dispatchEvent(new Event('change'));
                if(document.querySelectorAll('[data-balises-list] button').length!==1 || !document.querySelector('[data-balises-list]').textContent.includes('Balise inactive')) throw new Error('Filtre manuel incorrect');
                demarcheFilter.value='';demarcheFilter.dispatchEvent(new Event('change'));
                if(!document.querySelector('[data-balises-template-label]').hidden || templateFilter.value) throw new Error('Filtre template non réinitialisé');
                if(document.documentElement.scrollWidth>innerWidth+1) throw new Error('Débordement horizontal');
                result.textContent='BALISES_OK';
            }catch(error){result.textContent=error.stack;}
        });
        """
        with tempfile.TemporaryDirectory() as temporary:
            page=Path(temporary)/'balises.html'
            page.write_text(f'<!doctype html><meta charset="utf-8"><style>body{{margin:24px;font-family:Arial}}*{{box-sizing:border-box}}{css}</style><body>{body}<script>{mock}</script><script>{js}</script><script>{scenario}</script></body>',encoding='utf-8')
            for width in (540,1600,1920):
                with self.subTest(width=width):
                    result=subprocess.run([str(CHROME),'--headless=new','--disable-gpu','--no-first-run','--disable-background-networking',
                        f'--user-data-dir={temporary}/profile-{width}',f'--window-size={width},1000','--virtual-time-budget=5000','--dump-dom',page.as_uri()],
                        capture_output=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
                    dom=result.stdout.decode('utf-8',errors='replace')
                    self.assertTrue('<pre id="result">BALISES_OK</pre>' in dom,re.findall(r'<pre id="result">(.*?)</pre>',dom,re.S) or dom[-1000:])
