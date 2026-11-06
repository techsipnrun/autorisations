"""Parcours de la fiche dans Chrome, API simulée, sans BDD ni NAS."""
from pathlib import Path
import subprocess
import tempfile
from unittest import skipUnless

from django.template.loader import render_to_string
from django.test import SimpleTestCase


CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


@skipUnless(CHROME.exists(), "Chrome headless absent.")
class DocumentsInterfaceTests(SimpleTestCase):
    def test_ouvrir_verifier_et_afficher_le_rapport(self):
        src = Path(__file__).resolve().parents[3]
        body = render_to_string("backoffice/back_office_documents.html", {"csrf_token": "token-test"})
        javascript = (src / "backoffice/static/backoffice/js/back_office_documents.js").read_text(encoding="utf-8")
        css = (src / "backoffice/static/backoffice/css/back_office_documents.css").read_text(encoding="utf-8")
        mock = """
        let posts = 0, creations = 0;
        history.replaceState(null,'','#documents/templates/1');
        const template = {id:1,nom:'Projet d’arrêté',nature:'Arrêté directeur',
            chemin_relatif:'test.docx',destination_relative:'',nom_fichier:'',configuration_complete:false,configuration_errors:{destination_relative:['Vide'],nom_fichier:['Vide']},actif:true,demarches:[],demarche_ids:[],id_nature:3,rapport:null,
            date_verification:null,verification_url:'/verifier/',edition_url:'/enregistrer/'};
        window.fetch = async (url, options = {}) => {
            if(url.includes('/creer/')) {
                if(options.body.get('chemin_relatif')==='../invalide.docx') return new Response(JSON.stringify({erreur:'Vérifiez les champs.',fields:{chemin_relatif:[{message:'Saisissez un chemin relatif à Templates/.'}]}}),{status:400,headers:{'Content-Type':'application/json'}});
                creations++;
                if(options.body.get('id_nature')) throw new Error('Nature imposée');
                if(options.body.get('csrfmiddlewaretoken')!=='token-test') throw new Error('CSRF création absent');
                return new Response(JSON.stringify({template:{...template,id:4,nom:options.body.get('nom'),
                    id_nature:null,nature:'',chemin_relatif:options.body.get('chemin_relatif'),destination_relative:options.body.get('destination_relative'),
                    nom_fichier:options.body.get('nom_fichier'),configuration_complete:true,configuration_errors:{},demarches:[],demarche_ids:[]}}),
                    {status:201,headers:{'Content-Type':'application/json'}});
            }
            if(url.includes('/options/')) return new Response(JSON.stringify({filename_date:{year:'2026',day:'04-11-26'},nas_root:'//serveur/dev/',natures:[{id:3,nom:'Arrêté directeur'}],demarches:[{id:1,nom:'Démarche test'}]}),{headers:{'Content-Type':'application/json'}});
            if(url==='/enregistrer/') {
                template.nom=options.body.get('nom');template.chemin_relatif=options.body.get('chemin_relatif');
                template.destination_relative=options.body.get('destination_relative');template.nom_fichier=options.body.get('nom_fichier');
                template.configuration_complete=!!template.destination_relative && !!template.nom_fichier;template.configuration_errors={};
                return new Response(JSON.stringify({template}),{headers:{'Content-Type':'application/json'}});
            }
            if (options.method === 'POST') {
                if (options.headers['X-CSRFToken'] !== 'token-test') throw new Error('CSRF absent');
                posts++;
                template.rapport={valide:false,syntaxe_valide:true,analyse_complete:true,total:2,
                    compteurs:{CONNUE:1,A_RENSEIGNER:0,INCONNUE:1},
                    balises:[{code:'dossier.numero',statut:'CONNUE'},{code:'toto.foo',statut:'INCONNUE'}],
                    erreurs:['Balise inconnue : toto.foo.']};
                return new Response(JSON.stringify({templates:[template,
                    {...template,id:2,nom:'Modèle démarche test',demarche_ids:[1],demarches:['Démarche test']},
                    {...template,id:3,nom:'Modèle autre démarche',demarche_ids:[2],demarches:['Autre démarche']}]}),
                    {headers:{'Content-Type':'application/json'}});
            }
            return new Response(JSON.stringify({templates:[template]}), {headers:{'Content-Type':'application/json'}});
        };
        """
        scenario = """
        document.addEventListener('DOMContentLoaded', async () => {
            const result = document.createElement('pre');
            result.id = 'result';document.body.append(result);
            const attendre = async fn => {
                for (let i=0; i<50; i++) { if(fn()) return; await new Promise(r=>setTimeout(r,20)); }
                throw new Error('Attente expirée');
            };
            try {
                document.querySelector('[data-panel]').hidden = false;
                await attendre(()=>document.querySelector('[data-documents-liste] button'));
                if(document.querySelector('[data-document-fiche]').hidden || !document.querySelector('[data-document-nom]').textContent.includes('Projet')) throw new Error('Fiche non restaurée depuis URL');
                document.querySelector('[data-document-retour]').click();
                if(location.hash!=='#documents/templates') throw new Error('Retour catalogue non mémorisé');
                const statutFilter=document.querySelector('[data-documents-statut]');
                statutFilter.value='valide';statutFilter.dispatchEvent(new Event('change'));
                if(document.querySelectorAll('[data-documents-liste] button').length!==0) throw new Error('Filtre valide incorrect');
                statutFilter.value='a_corriger';statutFilter.dispatchEvent(new Event('change'));
                if(document.querySelectorAll('[data-documents-liste] button').length!==3) throw new Error('Filtre à corriger incorrect');
                statutFilter.value='';statutFilter.dispatchEvent(new Event('change'));
                const filtreDemarche=document.querySelector('[data-documents-demarche]');
                filtreDemarche.value='1';filtreDemarche.dispatchEvent(new Event('change'));
                if(document.querySelectorAll('[data-documents-liste] button').length!==2) throw new Error('Filtre démarche incorrect');
                const filtered=document.querySelector('[data-documents-liste]').textContent;
                if(!filtered.includes('Projet') || !filtered.includes('Modèle démarche test') || filtered.includes('Modèle autre démarche')) throw new Error('Templates globaux ou associés incorrects');
                filtreDemarche.value='';filtreDemarche.dispatchEvent(new Event('change'));
                if(document.querySelectorAll('[data-documents-liste] button').length!==3) throw new Error('Réinitialisation du filtre incorrecte');
                const recherche=document.querySelector('[data-documents-recherche]');
                recherche.value='aucun resultat';recherche.dispatchEvent(new Event('input'));
                if(document.querySelector('[data-documents-liste] button')) throw new Error('Recherche sans effet');
                recherche.value='';recherche.dispatchEvent(new Event('input'));
                document.querySelector('[data-documents-liste] button').click();
                if(location.hash!=='#documents/templates/1') throw new Error('Template non mémorisé dans URL');
                if(document.querySelector('[data-document-fiche]').hidden) throw new Error('Fiche masquée');
                if(!document.querySelector('[data-document-configuration]').textContent.includes('incomplète')) throw new Error('Configuration vide non signalée');
                if(document.querySelector('[data-document-configuration]').textContent.includes('corriger')) throw new Error('Liste des champs encore affichée');
                if(document.querySelectorAll('[data-document-informations] dd.is-invalid').length!==2) throw new Error('Champs absents non colorés');
                if(!document.querySelector('.bo-documents-identite').classList.contains('is-incomplete')) throw new Error('Bordure incomplète absente');
                document.querySelector('[data-document-edit]').click();
                await attendre(()=>!document.querySelector('[data-document-edition]').hidden);
                const edition=document.querySelector('[data-document-edition]');
                if(!document.querySelector('[data-document-nas-info]').dataset.tooltip.includes('//serveur/dev/')) throw new Error('Racine NAS absente');
                edition.elements.nom.value='Projet de test modifié';
                edition.elements.chemin_relatif.value='TEST/test_generation.docx';
                const destination=edition.querySelector('[data-token-field="destination_relative"]');
                const filename=edition.querySelector('[data-token-field="nom_fichier"]');
                const number=filename.querySelector('[data-token-choices] button');
                if(number.textContent!=='Numéro du dossier' || filename.querySelectorAll('[data-token-choices] [data-variable="dossier.numero"]').length!==1) throw new Error('Variables numéro en double');
                for(const [code,title] of [['date.annee','2026'],['date.jour','04-11-26'],['beneficiaire.identite','raison sociale']]) {
                    const choice=filename.querySelector(`[data-token-choices] [data-variable="${code}"]`);
                    if(!choice || !choice.title.includes(title)) throw new Error('Nouvelle variable ou infobulle absente');
                    choice.click();
                    const chip=filename.querySelector(`.bo-document-token[data-variable="${code}"]`);
                    if(!choice.disabled || !chip || !chip.title.includes(title)) throw new Error('Chip dynamique incorrecte');
                    chip.querySelector('button').click();
                }
                if(edition.elements.nom_fichier.value!=='.docx') throw new Error('Extension absente');
                destination.querySelector('[data-token-choices] button').click();
                if(!destination.querySelector('.bo-document-token') || !destination.querySelector('[data-token-choices] button').disabled) throw new Error('Chip non insérée');
                if(destination.querySelector('.bo-document-token > span').textContent!=='Emplacement du dossier /') throw new Error('Emplacement non explicite');
                const destinationEditor=destination.querySelector('[data-token-editor]');
                destinationEditor.append(document.createTextNode('/Work/'));destinationEditor.dispatchEvent(new Event('input'));
                const filenameEditor=filename.querySelector('[data-token-editor]');
                filenameEditor.textContent='DIR-I-';filenameEditor.dispatchEvent(new Event('input'));
                number.click();
                if(edition.elements.nom_fichier.value!=='DIR-I-{dossier.numero}.docx') throw new Error('Nom dynamique incorrect');
                filename.querySelector('.bo-document-token-remove').click();
                if(number.disabled || edition.elements.nom_fichier.value!=='DIR-I-.docx') throw new Error('Suppression de chip incorrecte');
                number.click();
                edition.querySelector('button[type=submit]').click();
                await attendre(()=>edition.hidden);
                if(!document.querySelector('[data-document-nom]').textContent.includes('modifié')) throw new Error('Édition non appliquée');
                if(!document.querySelector('[data-document-informations]').textContent.includes('TEST/test_generation.docx')) throw new Error('Chemin non actualisé');
                const infos=document.querySelector('[data-document-informations]');
                if(infos.querySelector('[data-variable="dossier.emplacement"]')?.textContent!=='Emplacement du dossier /' || !infos.textContent.includes('Work/')) throw new Error('Destination non actualisée');
                if(infos.querySelector('[data-variable="dossier.numero"]')?.textContent!=='Numéro du dossier' || !infos.textContent.includes('DIR-I-')) throw new Error('Nom du fichier non actualisé');
                if(infos.querySelector('.bo-document-token button')) throw new Error('Suppression disponible hors édition');
                if(!document.querySelector('[data-document-etat]').textContent.includes('Configuration complète')) throw new Error('Statut de configuration non actualisé');
                if(document.querySelector('.bo-documents-identite').classList.contains('is-incomplete') || document.querySelector('[data-document-informations] .is-invalid')) throw new Error('Anciennes erreurs conservées');
                document.querySelector('[data-document-edit]').click();
                await attendre(()=>!edition.hidden);
                if(edition.elements.nom_fichier.value!=='DIR-I-{dossier.numero}.docx' || !filename.querySelector('.bo-document-token')) throw new Error('Configuration perdue');
                document.querySelector('[data-document-annuler]').click();
                await attendre(()=>posts===1 && document.querySelector('[data-document-rapport]').textContent.includes('toto.foo'));
                const texte=document.querySelector('[data-document-rapport]').textContent;
                if(!texte.includes('2 Balises détectées') || !texte.includes('Syntaxe docxtpl valide') || !texte.includes('Template invalide')) throw new Error(texte);
                if(document.querySelector('[data-document-verifier]')) throw new Error('Bouton manuel encore présent');
                if(texte.includes('Dernière vérification')) throw new Error('Horodatage encore présent');
                const metric=document.querySelector('.bo-documents-metrics .is-success');
                const badge=document.querySelector('.bo-documents-table .is-success');
                if(getComputedStyle(metric).backgroundColor!==getComputedStyle(badge).backgroundColor) throw new Error('Couleurs différentes');
                document.querySelector('[data-document-retour]').click();
                if(document.querySelector('[data-documents-liste]').hidden) throw new Error('Retour liste impossible');
                if(!document.querySelector('[data-documents-liste]').textContent.includes('À corriger')) throw new Error('Statut liste non actualisé');
                document.querySelector('[data-documents-liste] button').click();
                if(posts!==1) throw new Error('Analyse répétée sur une simple ouverture de fiche');
                document.querySelector('[data-panel]').hidden=true;
                await new Promise(r=>setTimeout(r,30));
                document.querySelector('[data-panel]').hidden=false;
                await attendre(()=>posts===2);
                if(document.documentElement.scrollWidth>window.innerWidth+1) throw new Error('Débordement horizontal');
                await attendre(()=>document.querySelector('[data-panel]').getAttribute('aria-busy')!=='true');
                document.querySelector('[data-document-retour]').click();
                document.querySelector('[data-document-new]').click();
                await attendre(()=>location.hash==='#documents/templates/nouveau' && !edition.hidden);
                const retourCreation=document.querySelector('[data-document-retour]');
                if(retourCreation.disabled) throw new Error('Retour création désactivé');
                let abandonConfirmations=0;
                window.confirm=()=>{abandonConfirmations++;return false;};
                retourCreation.click();
                if(location.hash!=='#documents/templates/nouveau' || edition.hidden || abandonConfirmations!==1) throw new Error('Annulation abandon incorrecte');
                window.confirm=()=>{abandonConfirmations++;return true;};
                retourCreation.click();
                if(location.hash!=='#documents/templates' || !edition.hidden || abandonConfirmations!==2) throw new Error('Retour après confirmation incorrect');
                document.querySelector('[data-document-new]').click();
                await attendre(()=>!edition.hidden);
                if(edition.elements.id_nature.required || edition.elements.id_nature.value!=='') throw new Error('Nature obligatoire à la création');
                if(!edition.elements.id_nature.closest('label').textContent.includes('facultative')) throw new Error('Nature facultative non indiquée');
                document.querySelector('[data-document-annuler]').click();
                if(location.hash!=='#documents/templates' || !edition.hidden) throw new Error('Annulation création incorrecte');
                document.querySelector('[data-document-new]').click();
                await attendre(()=>!edition.hidden);
                edition.elements.nom.value='Nouveau modèle';edition.elements.chemin_relatif.value='TEST/nouveau.docx';
                for(const [field,value] of [['destination_relative','Test/Work/'],['nom_fichier','Nouveau']]) {
                    const editor=edition.querySelector(`[data-token-field="${field}"] [data-token-editor]`);editor.textContent=value;editor.dispatchEvent(new Event('input'));
                }
                edition.elements.chemin_relatif.value='../invalide.docx';
                edition.querySelector('[type=submit]').click();
                await attendre(()=>edition.elements.chemin_relatif.getAttribute('aria-invalid')==='true');
                if(document.activeElement!==edition.elements.chemin_relatif || !edition.elements.chemin_relatif.closest('label').querySelector('[data-document-field-error]')) throw new Error('Erreur chemin non ciblée');
                if(document.querySelector('[data-document-edition-status]').textContent) throw new Error('Erreur champ encore affichée en bas');
                await attendre(()=>!edition.querySelector('[type=submit]').disabled);
                edition.elements.chemin_relatif.value='TEST/nouveau.docx';
                edition.querySelector('[type=submit]').click();
                await attendre(()=>creations===1 && edition.hidden && location.hash==='#documents/templates/4');
                if(document.querySelector('[data-document-informations] .is-invalid')) throw new Error('Nature vide signalée en erreur');
                document.querySelector('[data-document-retour]').click();
                if(!document.querySelector('[data-documents-liste]').textContent.includes('Nouveau modèle')) throw new Error('Nouveau template absent du catalogue');
                result.textContent='DOCUMENTS_OK';
            } catch(error) { result.textContent=error.stack; }
        });
        """
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "documents.html"
            path.write_text(f'<!DOCTYPE html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{{font-family:Arial,sans-serif;margin:24px;background:#f3f6f3}}*{{box-sizing:border-box}}{css}</style><body>{body}<script>{mock}</script><script>{javascript}</script><script>{scenario}</script></body>', encoding="utf-8")
            for width in (540, 1600):
                with self.subTest(width=width):
                    screenshot = Path(tempfile.gettempdir()) / f"agida-documents-{width}.png"
                    result = subprocess.run([
                        str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run",
                        "--disable-background-networking", f"--user-data-dir={temporary}/profile-{width}",
                        f"--window-size={width},1200", f"--screenshot={screenshot}",
                        "--virtual-time-budget=5000", "--dump-dom", path.as_uri(),
                    ], capture_output=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
                    dom = result.stdout.decode("utf-8", errors="replace")
                    self.assertIn('<pre id="result">DOCUMENTS_OK</pre>', dom, dom[-2500:])
