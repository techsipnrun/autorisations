"""Éditeur Avis et aperçu, avec serveur local et sans écriture en BDD."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import tempfile
from threading import Thread
from unittest import skipUnless
from urllib.parse import urlsplit

from django.template.loader import render_to_string
from django.test import SimpleTestCase

from instruction.utils.avis_formulaires import CHOIX_IMPORT, configuration_standard, verifier_configuration, STRUCTURELS


CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


@skipUnless(CHROME.exists(), "Chrome headless indisponible.")
class BackOfficeAvisInterfaceTests(SimpleTestCase):
    def test_editeur_conditions_apercu_enregistrement_et_erreur(self):
        src = Path(__file__).resolve().parents[3]
        contenu = render_to_string("backoffice/back_office_avis.html", {"csrf_token": "test"})
        pages = {code: dict(champs=configuration_standard(code), standards=configuration_standard(code), structurels=sorted(STRUCTURELS), thematiques_par_demarche={"1": ["1"]}, choix={
            "nature_type": [{"valeur": "instance", "libelle": "Demande à une instance"}, {"valeur": "interne", "libelle": "Consultation en interne"}],
            "nature": [{"valeur": "1", "libelle": "Demande à une instance", "nature_type": "instance"}, {"valeur": "2", "libelle": "Consultation en interne", "nature_type": "interne"}],
            "thematique": [{"valeur": "1", "libelle": "Travaux"}, {"valeur": "2", "libelle": "Autre"}],
            "demarche": [{"valeur": "1", "libelle": "Travaux"}],
            "destinataire": [{"valeur": "CS", "libelle": "CS"}, {"valeur": "BCS", "libelle": "BCS"}],
            "expert_cs": [{"valeur": "true", "libelle": "Oui"}, {"valeur": "false", "libelle": "Non"}],
            "expert_externe": [{"valeur": "2", "libelle": "Conseil scientifique", "est_cs": True},
                               {"valeur": "3", "libelle": "une.adresse.mail.extremement.longue." * 12 + "@exemple.test", "est_cs": False}],
            "demandeur_avis": [{"valeur": "1", "libelle": "Instructeur test"}],
            **{cle: [{"valeur": valeur, "libelle": libelle} for valeur, libelle in choix] for cle, choix in CHOIX_IMPORT.items()},
        }) for code in ("dossier", "generique", "existant")}
        enregistres = []
        script = """
        window.addEventListener('load',async()=>{
            const sortie=document.createElement('pre');document.body.append(sortie);
            const assert=(ok,msg)=>{if(!ok)throw new Error(msg);};
            const attendre=async(predicat)=>{for(let i=0;i<60;i++){if(predicat())return;await new Promise(r=>setTimeout(r,35));}throw new Error('Attente trop longue');};
            window.confirm=()=>true;
            try {
                await attendre(()=>document.querySelectorAll('.bo-avis-field').length===11);
                const q=s=>document.querySelector(s);
                const champ=q('[data-code="note_demandeur"]');champ.open=true;
                const aide=champ.querySelectorAll('textarea')[0];aide.value='Aide personnalisée';aide.dispatchEvent(new Event('input'));
                const simulation=q('[data-avis-simulation] select');simulation.value='instance';simulation.dispatchEvent(new Event('change'));
                assert(q('[data-avis-apercu]').textContent.includes('Aide personnalisée'),'Aide dans aperçu');
                assert(q('#bo-avis-preview-nature')?.tagName==='SELECT','Vrai select de nature dans aperçu');
                assert(q('#bo-avis-preview-note_demandeur')?.tagName==='TEXTAREA','Zone de note fidèle au formulaire');
                const aideNote=q('[data-preview-code=note_demandeur] .avis-field-help');
                assert(aideNote&&aideNote.querySelector('[role=tooltip]').textContent==='Aide personnalisée','Aide en infobulle');
                assert(!q('[data-preview-code=note_demandeur] small'),'Pas d’aide sous le champ');
                aideNote.querySelector('button').focus();
                const bulle=aideNote.querySelector('[role=tooltip]');
                assert(getComputedStyle(bulle).display==='block'&&bulle.getBoundingClientRect().right<=innerWidth,'Infobulle au clavier contenue');
                assert(bulle.getBoundingClientRect().width<250,'Infobulle courte ajustée au texte');
                const texteAide=bulle.textContent;bulle.textContent='Une longue explication pour vérifier le retour à la ligne. '.repeat(20);
                aideNote.querySelector('button').blur();aideNote.querySelector('button').focus({preventScroll:true});
                assert(bulle.getBoundingClientRect().width<=Math.min(360,innerWidth-32)+1,'Infobulle longue limitée à la fenêtre');
                bulle.textContent=texteAide;
                assert(getComputedStyle(aideNote.querySelector('button')).cursor==='pointer','Pas de curseur aide');
                const dimensionInfo=aideNote.querySelector('button').getBoundingClientRect();
                assert(Math.abs(dimensionInfo.width-dimensionInfo.height)<.1,'Même cercle dans aperçu B-O');
                assert(getComputedStyle(aideNote.querySelector('button')).backgroundColor==='rgba(0, 0, 0, 0)','Aide transparente dans aperçu B-O');
                assert(aide.getBoundingClientRect().width<champ.querySelector('.bo-avis-field-body').getBoundingClientRect().width-1,'Texte court non étiré dans l’éditeur');
                assert(getComputedStyle(q('[data-preview-code=note_demandeur]')).alignItems==='flex-start','Note alignée en haut');
                const placeholder=Array.from(champ.querySelectorAll('label')).find(l=>l.textContent.startsWith('Texte indicatif')).querySelector('input');
                placeholder.value='Mon texte indicatif';placeholder.dispatchEvent(new Event('input'));
                assert(q('#bo-avis-preview-note_demandeur').placeholder==='Mon texte indicatif','Placeholder configuré en direct');
                const natureConfig=q('[data-code=nature]');natureConfig.open=true;
                const defautNature=natureConfig.querySelector('select');defautNature.value='2';defautNature.dispatchEvent(new Event('change'));
                assert(q('#bo-avis-preview-nature').value==='2'&&!q('#bo-avis-preview-expert_externe'),'Valeur initiale nature prioritaire sur scénario');
                assert(q('[data-code=expert_interne]').textContent.includes('Consultation en interne'),'Condition interne protégée visible');
                defautNature.value='';defautNature.dispatchEvent(new Event('change'));
                simulation.value='instance';simulation.dispatchEvent(new Event('change'));
                assert(!q('[data-avis-apercu] input[type=file]'),'Aucun téléversement possible dans aperçu');
                assert(q('[data-preview-code=pj_demande_avis] button').disabled,'Sélection de PJ purement visuelle');
                assert(q('[data-preview-code=pj_demande_avis] label').textContent.includes('*'),'Obligation à l’envoi visible');
                const mode=q('[data-avis-preview-mode] select');mode.value='brouillon';mode.dispatchEvent(new Event('change'));
                assert(!q('[data-preview-code=pj_demande_avis] label').textContent.includes('*'),'Obligation brouillon distincte');
                const expert=q('#bo-avis-preview-expert_externe');expert.value='2';expert.dispatchEvent(new Event('change'));
                assert(q('#bo-avis-preview-destinataire').value==='CS','Condition CS appliquée depuis le vrai select aperçu');
                assert(q('#bo-avis-preview-destinataire').getBoundingClientRect().width<100,'Select court non étiré');
                const preview=q('.bo-avis-preview');
                const expertLong=q('#bo-avis-preview-expert_externe');expertLong.value='3';expertLong.dispatchEvent(new Event('change'));
                assert(!q('#bo-avis-preview-destinataire'),'Destinataire masqué pour autre expert');
                assert(q('#bo-avis-preview-expert_externe').getBoundingClientRect().right<=preview.getBoundingClientRect().right,'Select long dans aperçu contenu');
                const ajout=Array.from(champ.querySelectorAll('button')).find(b=>b.textContent==='+ Cas conditionnel');
                ajout.scrollIntoView({block:'center',behavior:'instant'});
                const avantAjout=scrollY;assert(avantAjout>100,'Test de scroll en bas du formulaire');ajout.click();
                await new Promise(resolve=>requestAnimationFrame(resolve));
                assert(Math.abs(scrollY-avantAjout)<2,'Ajout de cas conserve le scroll');
                assert(parseFloat(getComputedStyle(q('.bo-avis-add-case')).marginTop)===parseFloat(getComputedStyle(document.documentElement).fontSize)/2,'Marge avant ajout de cas');
                const ouvert=q('[data-code="note_demandeur"]');
                assert(ouvert.open,'Champ reste ouvert pendant la modification');
                const cas=ouvert.querySelector('fieldset:last-of-type');
                const source=cas.querySelector('.bo-avis-condition select');source.focus({preventScroll:true});
                const avantCondition=scrollY;source.value='expert_externe';source.dispatchEvent(new Event('change'));
                await new Promise(resolve=>requestAnimationFrame(resolve));
                assert(Math.abs(scrollY-avantCondition)<2,'Changement de condition conserve le scroll');
                assert(document.activeElement.matches('.bo-avis-condition select'),'Focus du sélecteur restauré sans défilement');
                assert(parseFloat(getComputedStyle(q('.bo-avis-case .bo-avis-checks')).marginTop)===parseFloat(getComputedStyle(document.documentElement).fontSize)/2,'Marge avant réglages du cas');
                const selects=q('[data-code="note_demandeur"] fieldset:last-of-type .bo-avis-condition').querySelectorAll('select');selects[2].value='3';selects[2].dispatchEvent(new Event('change'));
                const labelCas=Array.from(q('[data-code="note_demandeur"] fieldset').querySelectorAll('label')).find(l=>l.textContent.startsWith('Libellé dans ce cas')).querySelector('input');
                labelCas.value='Autre libellé';labelCas.dispatchEvent(new Event('input'));
                assert(q('[data-preview-code=note_demandeur] label').textContent.startsWith('Autre libellé'),'Libellé conditionnel appliqué');
                labelCas.value='';labelCas.dispatchEvent(new Event('input'));
                assert(q('[data-preview-code=note_demandeur] label').textContent.startsWith('Note'),'Retour au libellé principal');
                const placeholderCas=Array.from(q('[data-code="note_demandeur"] fieldset').querySelectorAll('label')).find(l=>l.textContent.startsWith('Texte indicatif')).querySelector('input');
                placeholderCas.value='Indication pour ce cas';placeholderCas.dispatchEvent(new Event('input'));
                assert(q('#bo-avis-preview-note_demandeur').placeholder==='Indication pour ce cas','Placeholder du cas utilisé');
                placeholderCas.value='';placeholderCas.dispatchEvent(new Event('input'));
                assert(q('#bo-avis-preview-note_demandeur').placeholder==='Mon texte indicatif','Placeholder vide reprend le défaut');
                const themeConfig=q('[data-code=thematique]');themeConfig.open=true;
                assert(!themeConfig.textContent.includes('Personnaliser la liste'),'Plus de liste indépendante dans le formulaire');
                assert(themeConfig.querySelector('a[href="#avis/thematiques"]'),'Lien vers le catalogue unique');
                const accesCatalogue=themeConfig.querySelector('.bo-avis-catalogue-link');
                assert(accesCatalogue&&accesCatalogue.querySelector('svg')&&accesCatalogue.querySelector('small'),'Accès catalogue en carte avec icône et sous-titre');
                assert(getComputedStyle(accesCatalogue).textDecorationLine==='none','Carte sans soulignement de lien');
                assert(themeConfig.querySelector('.bo-avis-add-case').getBoundingClientRect().top>=accesCatalogue.getBoundingClientRect().bottom,'Cas conditionnel sous la carte catalogue');
                assert(themeConfig.querySelectorAll('.bo-avis-catalogue-link').length===1,'Un seul accès catalogue par champ');
                const demarcheScenario=q('[data-preview-source=demarche]');demarcheScenario.value='1';demarcheScenario.dispatchEvent(new Event('change'));
                assert(q('#bo-avis-preview-thematique option[value="1"]')&&!q('#bo-avis-preview-thematique option[value="2"]'),'Répartition du catalogue dans aperçu');
                document.querySelectorAll('.bo-avis select').forEach(select=>{
                    if(!select.getClientRects().length)return;
                    const parent=select.closest('fieldset, .bo-avis-preview, .bo-avis-toolbar, .bo-avis-field');
                    assert(!parent||select.getBoundingClientRect().right<=parent.getBoundingClientRect().right+1,'Select contenu même avec email long');
                });
                assert(q('.bo-avis').classList.contains('is-dirty'),'Avertissement non enregistré');
                q('[data-avis-enregistrer]').click();
                await attendre(()=>q('[data-avis-message]').classList.contains('is-error'));
                assert(q('[data-avis-message]').textContent.includes('HTTP 500')&&!q('[data-avis-message]').textContent.includes('Unexpected token'),'Erreur HTML expliquée sans erreur de parsing JSON');
                assert(q('[data-code="note_demandeur"] textarea').value==='Aide personnalisée','Erreur réseau conserve la saisie');
                q('[data-avis-enregistrer]').click();
                await attendre(()=>q('[data-avis-message]').textContent.startsWith('Formulaire enregistré'));
                assert(!q('.bo-avis').classList.contains('is-dirty'),'Enregistrement confirmé');
                const contexte=q('[data-avis-contexte]');contexte.value='generique';contexte.dispatchEvent(new Event('change'));
                await attendre(()=>document.querySelectorAll('.bo-avis-field').length===12);
                assert(q('[data-code="demarche"]'),'Contexte générique distinct');
                assert(!q('.bo-avis-preview-draft'),'Pas de bouton brouillon pour aperçu générique');
                contexte.value='existant';contexte.dispatchEvent(new Event('change'));
                await attendre(()=>document.querySelectorAll('.bo-avis-field').length===13);
                assert(q('[data-code="demandeur_avis"]'),'Champ instructeur de l’import');
                assert(q('#bo-avis-preview-date_demande_avis').type==='datetime-local','Aperçu date fidèle à l’import');
                assert(q('[data-preview-code=reponse] input[type=radio]:checked').value==='favorable','Vrais choix de réponse dans aperçu');
                const natureImport=q('#bo-avis-preview-nature');natureImport.value='1';natureImport.dispatchEvent(new Event('change'));
                const expertImport=q('#bo-avis-preview-expert_externe');expertImport.value='2';expertImport.dispatchEvent(new Event('change'));
                assert(q('#bo-avis-preview-publication_raa').value==='a_publier','Condition et défaut RAA de l’import');
                assert(q('#bo-avis-preview-numero_avis_externe').type==='text','Référence externe dans aperçu');
                assert(q('[data-preview-code=numero_avis_externe] .avis-field-help [role=tooltip]').textContent.includes('numéro par défaut'),'Aide numéro CS dans B-O');
                assert(!q('.bo-avis-preview-draft'),'Import sans brouillon');
                const fiche=q('[data-code="note_demandeur"]');fiche.open=true;
                assert(fiche.textContent.includes('Obligatoire à l’enregistrement'),'Obligation import explicite');
                assert(!fiche.textContent.includes('Obligatoire à l’envoi'),'Pas de validation d’envoi pour import');
                q('[data-avis-enregistrer]').click();
                await attendre(()=>q('[data-avis-message]').classList.contains('is-error'));
                q('[data-avis-enregistrer]').click();
                await attendre(()=>q('[data-avis-message]').textContent.startsWith('Formulaire enregistré'));
                const champs=q('[data-avis-champs]').getBoundingClientRect();
                document.querySelectorAll('.bo-avis-field').forEach(carte=>assert(carte.getBoundingClientRect().right<=champs.right+1,'Pas de débordement des cartes'));
                sortie.textContent='BACK_OFFICE_AVIS_OK';
            }catch(erreur){sortie.textContent='ECHEC: '+erreur.message;}
        });
        """
        page = f'''<!doctype html><html><head><meta charset="utf-8">
            <link rel="stylesheet" href="/static/backoffice/css/back_office.css">
            <link rel="stylesheet" href="/static/backoffice/css/back_office_avis.css">
            <link rel="stylesheet" href="/static/instruction/css/avis_formulaires.css">
            <script src="/static/instruction/js/avis_formulaires.js"></script>
            <script src="/static/backoffice/js/back_office_avis.js"></script></head>
            <body><div class="back-office-layout"><aside class="back-office-sidebar"></aside><main class="back-office-content"><section class="back-office-panel" data-panel="avis">{contenu}</section></main></div><script>{script}</script></body></html>'''.encode("utf-8")

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def repondre(self, contenu, mime="application/json", status=200):
                self.send_response(status); self.send_header("Content-Type", mime); self.end_headers(); self.wfile.write(contenu)

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == "/":
                    self.repondre(page, "text/html; charset=utf-8")
                elif path.startswith(("/static/instruction/", "/static/backoffice/")):
                    fichier = src / path.split("/")[2] / "static" / path.removeprefix("/static/")
                    self.repondre(fichier.read_bytes(), "text/css" if fichier.suffix == ".css" else "application/javascript")
                elif path.startswith("/back-office/avis/formulaires/"):
                    self.repondre(json.dumps(pages[path.strip("/").split("/")[-1]]).encode())
                else:
                    self.send_error(404)

            def do_POST(self):
                donnees = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                verifier_configuration(self.path.strip("/").split("/")[-1], donnees["champs"])
                enregistres.append(donnees)
                if len(enregistres) % 2:
                    self.repondre(b'<!DOCTYPE html><html><body>Erreur serveur</body></html>', mime="text/html", status=500)
                else:
                    self.repondre(json.dumps({"success": True}).encode())

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            for largeur in (540, 1600, 2200):
                with self.subTest(largeur=largeur), tempfile.TemporaryDirectory(prefix="agida-bo-avis-") as profil:
                    resultat = subprocess.run([str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run", "--disable-background-networking",
                        f"--user-data-dir={profil}", f"--window-size={largeur},1000", "--virtual-time-budget=6000", "--dump-dom", f"http://127.0.0.1:{server.server_port}/#avis"],
                        capture_output=True, timeout=45, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    dom = resultat.stdout.decode("utf-8", errors="replace")
                    self.assertIn(">BACK_OFFICE_AVIS_OK</pre>", dom, dom[-1800:])
            self.assertEqual(len(enregistres), 12)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)
