"""Parcours navigateur du formulaire d'avis, sans API, mail, base ni NAS."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from base64 import b64decode
from pathlib import Path
import subprocess
import tempfile
from threading import Thread
from types import SimpleNamespace
from unittest import skipUnless
from urllib.parse import urlsplit

from django.template import Context, Template
from django.template.loader import get_template, render_to_string
from django.test import SimpleTestCase


CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


@skipUnless(CHROME.exists(), "Chrome headless indisponible.")
class FormulaireAvisInterfaceTests(SimpleTestCase):
    def test_creation_instance_consultation_interne_et_edition_brouillon(self):
        src = Path(__file__).resolve().parents[2]
        natures = [SimpleNamespace(id=1, nature="Demande à une instance"), SimpleNamespace(id=2, nature="Consultation en interne")]
        thematique = SimpleNamespace(id=3, thematique="Travaux")
        cs = SimpleNamespace(id=20, nom=None, prenom=None, raison_sociale="Conseil scientifique", organisation=None, email="tres.longue.adresse." * 12 + "@exemple.test")
        autre = SimpleNamespace(id=21, nom="COLLIN", prenom="Gérard", raison_sociale=None, organisation=None, email="gerard@example.test")
        fichier = SimpleNamespace(id=30, titre="un_tres_long_nom_de_piece_jointe_" * 8 + ".pdf", emplacement="Avis/instance/Annexes/")
        avis = SimpleNamespace(id=1025, statut="Brouillon", id_avis_nature=natures[0], id_avis_thematique=thematique,
            id_expert=SimpleNamespace(id_contact_externe=cs, id_instructeur=None), destinataire="BCS", note="Note existante",
            formulation="Formulation conservée", id_projet_avis=fichier, id_projet_acte=fichier, id_rapport_instance=fichier)
        contexte = {
            "dossier": SimpleNamespace(numero=30655697), "natures": natures, "thematiques": [thematique],
            "contacts_externes": [cs, autre], "instructeurs": [SimpleNamespace(id=10, email="interne@example.test")],
            "csrf_token": "test",
            "reservation_cle": "6ae3c209-3546-407f-a7df-b07cdf02c53d",
        }
        source = get_template("instruction/instruction_dossier_ajouter_avis.html").template.source
        entete = source[source.index('<div class="header_nouvelle_demande_avis">'):source.index('{% include "instruction/refacto/demande_avis_formulaire.html" %}')]
        pages = {}
        for scenario in ("nouveau", "nouveau_brouillon", "interne", "brouillon", "envoi", "apercus"):
            contexte["avis"] = avis if scenario in ("brouillon", "envoi", "apercus") else None
            if scenario == "apercus":
                contexte["avis"] = SimpleNamespace(**{**vars(avis),
                    "id_projet_avis": SimpleNamespace(id=31, titre="projet.docx", emplacement=fichier.emplacement),
                    "id_rapport_instance": SimpleNamespace(id=32, titre="photo.png", emplacement=fichier.emplacement)})
            contexte["reservation"] = SimpleNamespace(id=contexte["reservation_cle"], numero=1026)
            contexte["numero_avis"] = avis.id if contexte["avis"] else 1026
            contexte["pieces_complementaires"] = [SimpleNamespace(id_document=SimpleNamespace(id=pk, titre=fichier.titre, emplacement=fichier.emplacement)) for pk in (40, 41)] if contexte["avis"] else []
            contenu = Template(entete).render(Context(contexte)) + render_to_string("instruction/refacto/demande_avis_formulaire.html", contexte)
            pages[f"/{scenario}/"] = f'''<!doctype html><html lang="fr"><head><meta charset="utf-8">
            <link rel="stylesheet" href="/static/instruction/css/instruction_dossier_ajouter_avis.css">
            <link rel="stylesheet" href="/static/instruction/css/dossier.css">
            <script src="/static/instruction/js/ajouter_avis.js"></script>
            <script src="/static/instruction/js/document_hover_preview.js"></script>
            </head><body data-scenario="{scenario}"><header class="navigation_header" style="position:fixed;top:0;height:64px;width:100%;background:white;z-index:10001"></header><div class="avis"><div class="form_ajout_demande_avis">{contenu}</div></div>
            <script>{self.script()}</script></body></html>'''

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                path = urlsplit(self.path).path
                if path in pages:
                    data, mime = pages[path].encode("utf-8"), "text/html; charset=utf-8"
                elif path.startswith("/static/instruction/"):
                    fichier = src / "instruction/static/instruction" / path.removeprefix("/static/instruction/")
                    data = fichier.read_bytes()
                    mime = {".js": "application/javascript", ".css": "text/css", ".svg": "image/svg+xml"}.get(fichier.suffix, "image/png")
                elif path.endswith("/photo.png/"):
                    data = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN1sAAAAASUVORK5CYII=")
                    mime = "image/png"
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.end_headers()
                self.wfile.write(data)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for scenario in ("nouveau", "nouveau_brouillon", "interne", "brouillon", "envoi", "apercus"):
                with self.subTest(scenario=scenario), tempfile.TemporaryDirectory(prefix="agida-form-avis-") as profile:
                    resultat = subprocess.run([
                        str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run", "--disable-background-networking",
                        f"--user-data-dir={profile}", "--window-size=" + ("360,400" if scenario == "apercus" else "540,1000"), "--virtual-time-budget=3000", "--dump-dom",
                        f"http://127.0.0.1:{server.server_port}/{scenario}/",
                    ], capture_output=True, timeout=45, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    dom = resultat.stdout.decode("utf-8", errors="replace")
                    self.assertTrue('>FORMULAIRE_AVIS_OK</pre>' in dom, dom[-2200:])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    @staticmethod
    def script():
        return """
        window.addEventListener('load',async()=>{
            const sortie=document.createElement('pre');document.body.append(sortie);
            const assert=(ok,message)=>{if(!ok) throw new Error(message);};
            const form=document.getElementById('form-avis');
            const q=selecteur=>form.querySelector(selecteur);
            const visible=selecteur=>q(selecteur).getClientRects().length>0;
            const choisir=(selecteur,valeur)=>{q(selecteur).value=valeur;q(selecteur).dispatchEvent(new Event('change'));};
            let envoi;
            form.submit=()=>{envoi={url:form.action,donnees:new FormData(form)};};
            window.confirm=()=>true;
            const selectionFichier=(input,nom)=>{
                const transfert=new DataTransfer();transfert.items.add(new File(['contenu'],nom));input.files=transfert.files;
                input.dispatchEvent(new Event('change'));
            };
            try {
                const scenario=document.body.dataset.scenario;
                assert(getComputedStyle(q('.btn-brouillon')).backgroundColor==='rgb(75, 85, 99)','Bouton Brouillon gris foncé');
                if(scenario==='apercus') {
                    const attendre=()=>new Promise(resolve=>setTimeout(resolve,70));
                    const controle=q('#bloc_pj_projet_acte [data-pj-controle]');
                    const loupe=controle.querySelector('.document-apercu-trigger');
                    const popover=controle.querySelector('.document-apercu-popover');
                    let appels=0;
                    window.fetch=async()=>{appels++;return new Response(new Blob(['%PDF-1.4'],{type:'application/pdf'}));};
                    assert(!q('#bloc_pj_demande_avis .document-apercu-trigger'),'Pas de loupe sur Word');
                    assert(appels===0,'Aperçu chargé seulement au clic');
                    loupe.click();await attendre();
                    assert(controle.classList.contains('is-preview-open')&&loupe.getAttribute('aria-expanded')==='true','Ouverture de l’aperçu');
                    assert(popover.querySelector('embed')?.type==='application/pdf','PDF chargé avec le composant commun');
                    const cadre=popover.getBoundingClientRect();
                    assert(cadre.left>=11&&cadre.right<=innerWidth-11,'Aperçu contenu horizontalement dans la petite fenêtre');
                    assert(cadre.top>=75&&cadre.bottom<=innerHeight-11,'Aperçu sous la navbar et contenu en hauteur');
                    loupe.click();assert(!controle.classList.contains('is-preview-open'),'Second clic ferme');
                    loupe.click();await attendre();
                    assert(appels===1,'PDF non retéléchargé à chaque ouverture');
                    const image=q('#bloc_pj_rapport_cs .document-apercu-trigger');image.click();await attendre();
                    assert(!controle.classList.contains('is-preview-open'),'Un seul aperçu ouvert');
                    const img=q('#bloc_pj_rapport_cs .document-apercu-popover img');
                    assert(img&&img.complete&&img.naturalWidth>0,'Image réellement chargée');
                    document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));
                    assert(!form.querySelector('.is-preview-open'),'Échap ferme l’aperçu');
                    loupe.click();document.body.click();assert(!controle.classList.contains('is-preview-open'),'Clic extérieur ferme');
                    loupe.click();window.dispatchEvent(new Event('resize'));window.dispatchEvent(new Event('scroll'));await attendre();
                    const apres=popover.getBoundingClientRect();assert(apres.right<=innerWidth-11&&apres.bottom<=innerHeight-11,'Repositionnement après défilement/redimensionnement');
                    const input=q('#pj_projet_acte');input.click=()=>{};
                    q('[data-remplacer-pj="pj_projet_acte"]').click();assert(!controle.classList.contains('is-preview-open'),'Remplacer ferme l’aperçu');
                    selectionFichier(input,'nouvel-acte.pdf');assert(loupe.hidden,'Aucun aperçu de l’ancien fichier sous le nouveau titre');
                    sortie.textContent='FORMULAIRE_AVIS_OK';return;
                }
                if(['nouveau','nouveau_brouillon','interne'].includes(scenario)) {
                    assert(Array.from(form.querySelectorAll('.attribut_avis')).filter(el=>el.getClientRects().length).length===2,'Seulement nature et thématique au départ');
                    assert(!q('.btn-dropdown')&&!q('.btn-generer-numero')&&!visible('.avis-form-actions'),'Plus de génération ni de menu déroulant');
                    assert(document.querySelector('h2').textContent.includes('n° 1026'),'Numéro réservé visible dès l’ouverture');
                    choisir('#thematique','3');
                    if(scenario==='nouveau' || scenario==='nouveau_brouillon') {
                        choisir('#nature','1');choisir('#expert_externe','20');
                        assert(visible('#bloc_expert_externe')&&visible('.avis-form-actions'),'Sélection instance et deux actions visibles');
                        assert(visible('#bloc_note_avis')&&visible('#bloc_formulation_avis')&&visible('#bloc_pj_demande_avis')&&visible('#bloc_autres_pj_avis'),'Création instance avec formulaire complet');
                        assert(q('.avis-rappel-numero').textContent.includes('1026'),'Rappel du numéro réservé avant création du brouillon');
                        assert(getComputedStyle(q('.avis-rappel-numero')).color==='rgb(139, 30, 30)','Rappel rouge foncé');
                        document.querySelector('.avis').style.width='1000px';
                        const labelProjet=q('#label_pj_demande_avis').getBoundingClientRect();
                        const fichierProjet=q('#pj_demande_avis').getBoundingClientRect();
                        assert(Math.abs((labelProjet.top+labelProjet.bottom-fichierProjet.top-fichierProjet.bottom)/2)<1,'Sélecteur aligné verticalement avec le libellé sans tenir compte du rappel');
                        assert(q('.avis-rappel-numero').getBoundingClientRect().top>=Math.max(labelProjet.bottom,fichierProjet.bottom),'Rappel sur sa propre ligne sous le libellé et le sélecteur');
                        const champs=Array.from(form.querySelectorAll('.attribut_avis')).filter(el=>el.getClientRects().length).map(el=>el.querySelector('select,input,textarea').id);
                        assert(champs.join(',')==='nature,expert_externe,destinataire,thematique,note_demandeur,pj_demande_avis,pj_projet_acte,pj_rapport_cs,pj_lie_avis,formulation_avis','Ordre des champs instance');
                        assert(q('.avis-form-actions').firstElementChild.classList.contains('btn-brouillon'),'Brouillon avant Envoyer');
                        assert(q('#destinataire').value==='CS','CS sélectionné par défaut');
                        choisir('#expert_externe','21');
                        document.querySelector('.avis').style.width='900px';
                        assert(q('#expert_externe').getBoundingClientRect().width<400,'Select dimensionné au choix courant, sans remplir la ligne');
                        choisir('#expert_externe','20');
                        for(const largeur of [300,480]) {
                            document.querySelector('.avis').style.width=largeur+'px';
                            const label=q('#bloc_expert_externe label');
                            assert(label.getBoundingClientRect().height<25,'Label expert sur une ligne');
                            assert(q('#expert_externe').getBoundingClientRect().right<=form.getBoundingClientRect().right+1,'Select contraint malgré le long email');
                        }
                        if(scenario==='nouveau') {
                            q('.btn-confirmer-envoi').click();
                            assert(!envoi,'Envoi refusé sans projets obligatoires');
                            selectionFichier(q('#pj_demande_avis'),'projet.docx');
                            q('.btn-confirmer-envoi').click();
                            assert(!envoi,'Projet d’acte également obligatoire');
                            selectionFichier(q('#pj_projet_acte'),'acte.pdf');
                            q('.btn-confirmer-envoi').click();
                            assert(envoi?.url.includes('confirmer_ajout_avis'),'Envoi direct possible sans brouillon préalable');
                        } else {
                            q('#formulation_avis').value='';
                            q('.btn-brouillon').click();
                            assert(envoi?.url.includes('enregistrer_brouillon_avis'),'Brouillon possible sans projets ni formulation');
                        }
                        assert(envoi.donnees.get('reservation')==='6ae3c209-3546-407f-a7df-b07cdf02c53d','Clé de réservation stable transmise depuis Consultation');
                    } else {
                        choisir('#nature','2');choisir('#expert_interne','10');
                        assert(visible('#bloc_note_avis')&&visible('#bloc_autres_pj_avis')&&visible('#bloc_formulation_avis'),'Formulaire interne détaillé');
                        assert(!visible('#bloc_pj_demande_avis')&&!q('.btn-generer-numero'),'Pas de génération ni projet d’instance en création interne');
                        assert(q('#label_autres_pj').textContent==='Pièces jointes à transmettre :','Libellé interne');
                        assert(q('#formulation_avis').value==='Bonjour, je sollicite votre avis sur le dossier 30655697…','Message interne contextualisé');
                        selectionFichier(q('#pj_lie_avis'),'piece.pdf');
                        selectionFichier(q('#pj_lie_avis'),'deuxieme.pdf');
                        selectionFichier(q('#pj_lie_avis'),'a-retirer.pdf');
                        assert(q('#pj_lie_avis').files.length===3,'Sélections successives cumulées');
                        q('[data-pj-a-enregistrer]').lastElementChild.querySelector('button').click();
                        assert(q('#pj_lie_avis').files.length===2,'Retrait avant enregistrement');
                        q('.btn-confirmer-envoi').click();
                        assert(envoi?.url.includes('confirmer_ajout_avis'),'Envoi interne conservé');
                        assert(envoi.donnees.get('pj_lie_avis').name==='piece.pdf','PJ interne transmise');
                        assert(envoi.donnees.getAll('pj_lie_avis').length===2,'Toutes les PJ sélectionnées sont transmises');
                    }
                } else {
                    assert(document.querySelector('.header_nouvelle_demande_avis h2').textContent.includes('1025'),'Numéro du brouillon dans le titre');
                    assert(q('#destinataire').value==='BCS','BCS enregistré conservé');
                    assert(q('#nature').disabled,'Nature du brouillon non modifiable');
                    assert(q('[data-pj-enregistrees]').querySelectorAll('[data-pj-controle]').length===2,'Toutes les PJ enregistrées sont visibles');
                    assert(q('[data-pj-enregistrees]').getBoundingClientRect().top>=q('#pj_lie_avis').getBoundingClientRect().bottom,'Liste des PJ sous le sélecteur');
                    assert(visible('#bloc_pj_demande_avis')&&visible('#bloc_pj_projet_acte')&&visible('#bloc_formulation_avis'),'Edition complète');
                    assert(q('.avis-rappel-numero').textContent.includes('1025'),'Rappel du numéro dans le document');
                    assert(q('#pj_demande_avis').hidden,'Pas de choisir un fichier visible quand une PJ existe');
                    for(const [bloc,source] of [['bloc_pj_demande_avis','id_projet_avis'],['bloc_pj_projet_acte','id_projet_acte'],['bloc_pj_rapport_cs','id_rapport_instance']]) {
                        assert(q('#'+bloc+' [data-supprimer-pj]').dataset.pjSource===source,'Source de suppression spécifique au champ '+bloc);
                    }
                    assert(q('[data-pj-enregistrees] [data-supprimer-pj]').dataset.pjSource==='annexe','Source annexe indépendante des champs principaux');
                    for(const largeur of [300,480]) {
                        document.querySelector('.avis').style.width=largeur+'px';
                        for(const ligne of form.querySelectorAll('.avis-pj-ligne')) {
                            assert(ligne.getBoundingClientRect().right<=form.getBoundingClientRect().right+1,'PJ contenue sur petit écran');
                            const titre=ligne.querySelector('[data-pj-titre]');
                            assert(titre.clientWidth<titre.scrollWidth,'Titre long tronqué');
                            assert(titre.getBoundingClientRect().height<30,'Titre sur une ligne');
                        }
                    }
                    if(scenario==='brouillon') {
                        const input=q('#remplacer_pj_40');let ouvert=0;input.click=()=>ouvert++;
                        q('[data-remplacer-pj="remplacer_pj_40"]').click();assert(ouvert===1,'Remplacer ouvre le sélecteur');
                        selectionFichier(input,'nouvelle-piece.pdf');
                        assert(input.closest('[data-pj-controle]').textContent.includes('nouvelle-piece.pdf'),'Nom de remplacement visible');
                        let terminerSuppression;
                        let sourceSupprimee;
                        window.fetch=(url,options)=>{sourceSupprimee=options.body.get('source');return new Promise(resolve=>{terminerSuppression=resolve;});};
                        q('#bloc_pj_rapport_cs [data-supprimer-pj]').click();
                        assert(sourceSupprimee==='id_rapport_instance','Le clic sur le rapport CS transmet uniquement cette source');
                        assert(!document.querySelector('[data-avis-loading]').hidden,'Chargement visible pendant la suppression');
                        terminerSuppression(new Response(JSON.stringify({success:false,error:'Suppression refusée'}),{status:403}));
                        await new Promise(resolve=>setTimeout(resolve,30));
                        assert(document.querySelector('[data-avis-loading]').hidden,'Chargement masqué si suppression échouée');
                        assert(!q('.avis-form-erreur').hidden,'Erreur de suppression visible sans perdre les saisies');
                        q('.btn-brouillon').click();
                        assert(!document.querySelector('[data-avis-loading]').hidden,'Chargement visible pendant la sauvegarde');
                        assert(envoi?.donnees.get('remplacer_pj_40').name==='nouvelle-piece.pdf','Remplacement transmis au brouillon');
                    } else {
                        q('.btn-confirmer-envoi').click();
                        assert(envoi?.url.includes('/confirmer-avis/1025/'),'Envoi du brouillon conservé sans recharger ses PJ');
                        assert(envoi.donnees.get('formulation_avis')==='Formulation conservée','Texte enregistré conservé');
                    }
                }
                assert(envoi.donnees.get('mode_contact')==='Application','Mode Application imposé');
                assert(envoi.donnees.get('nature')==='1'||scenario==='interne','Nature verrouillée tout de même transmise');
                sortie.textContent='FORMULAIRE_AVIS_OK';
            } catch(erreur) {sortie.textContent='FORMULAIRE_AVIS_ERREUR: '+erreur.message;}
        });
        """
