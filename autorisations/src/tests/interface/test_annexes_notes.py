"""Upload des annexes Notes dans Chrome, sans NAS ni service distant."""
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import tempfile
from threading import Thread
from types import SimpleNamespace
from unittest import skipUnless
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth.models import User
from django.template.loader import render_to_string
from django.test import SimpleTestCase

from autorisations.models.models_documents import Document

CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


@skipUnless(CHROME.exists(), "Chrome headless indisponible.")
class AnnexesNotesInterfaceTests(SimpleTestCase):
    def test_chargement_erreur_retentative_et_succes(self):
        src = Path(__file__).resolve().parents[2]
        annexe = Document(id=3, titre="existant.pdf", emplacement="Dossier/Annexes/", date=datetime(2026, 10, 15, tzinfo=timezone.utc))
        annexe.depose_par, annexe.peut_supprimer = "Louis Calu", True
        bloc = render_to_string("instruction/refacto/notes_annexes.html", {
            "dossier": SimpleNamespace(id=12, numero=123456, emplacement="Dossier/"),
            "request": SimpleNamespace(user=User(username="louis", is_superuser=True)),
            "csrf_token": "test", "annexes_instructeur": [annexe], "NAS_ROOT": "//nas/",
        })
        document = render_to_string("instruction/refacto/file_hover_preview.html", {
            "fichier_emplacement": "Dossier/Annexes/",
            "fichier_titre": "piece_jointe_avec_un_titre_extremement_long_" * 8 + ".pdf",
            "correction_form_id": 1,
        })
        script = """
        // Chrome --dump-dom ne cadence pas les frames après chaque navigation.
        // Garder l'ordonnancement asynchrone pour tester la vraie restauration du scroll.
        window.requestAnimationFrame=callback=>setTimeout(()=>callback(performance.now()),16);
        let terminer, appels=0, donnees;
        window.fetch = async (url, options) => {
            appels++; donnees=options.body;
            return new Promise(resolve=>{terminer=resolve;});
        };
        window.confirm=()=>false;
        window.addEventListener('load', async()=>{
            const sortie=document.createElement('pre');document.body.append(sortie);
            const assert=(ok, message)=>{if(!ok) throw new Error(message);};
            const wait=()=>new Promise(resolve=>setTimeout(resolve,30));
            const input=document.querySelector('.annexe-input');
            const form=input.form;
            const statut=document.querySelector('[data-annexe-upload-status]');
            const attente=document.querySelector('[data-notes-loading]');
            const loader=attente.querySelector('.envoi-acte-spinner');
            const choisir=nom=>{
                const transfert=new DataTransfer();transfert.items.add(new File(['contenu'],nom,{type:'application/pdf'}));
                input.files=transfert.files;input.dispatchEvent(new Event('change'));
            };
            try {
                if(sessionStorage.getItem('upload-termine')) {
                    await new Promise(resolve=>setTimeout(resolve,120));
                    assert(attente.hidden && statut.hidden && !input.disabled,'Chargement arrêté après succès');
                    assert(sessionStorage.getItem('notes-scroll:/')===null,'Position consommée après rechargement');
                    assert(Math.abs(window.scrollY-Number(sessionStorage.getItem('scroll-attendu')))<2,'Position restaurée après rechargement : '+window.scrollY+' / '+sessionStorage.getItem('scroll-attendu'));
                    assert(sessionStorage.getItem('chargement-jusqua-navigation')==='oui','Chargement conservé jusqu’à la navigation');
                    if(sessionStorage.getItem('suppression-terminee')) {
                        assert(sessionStorage.getItem('chargement-suppression')==='oui','Chargement conservé pendant la suppression');
                        sortie.textContent='ANNEXES_NOTES_OK';return;
                    }
                    const supprimer=document.querySelector('.btn-supprimer-annexe');
                    supprimer.click();
                    assert(attente.hidden && sessionStorage.getItem('notes-scroll:/')===null,'Suppression annulée : aucun chargement ni navigation');
                    window.scrollTo(0,600);
                    sessionStorage.setItem('scroll-attendu',String(window.scrollY));
                    sessionStorage.setItem('suppression-terminee','1');
                    window.confirm=()=>true;
                    window.addEventListener('pagehide',()=>{
                        sessionStorage.setItem('chargement-suppression',!attente.hidden ? 'oui':'non');
                    });
                    supprimer.click();
                    assert(!attente.hidden && attente.textContent.includes('Suppression de l’annexe'),'Suppression confirmée : chargement plein écran');
                    assert(Number(sessionStorage.getItem('notes-scroll:/'))===window.scrollY,'Position mémorisée avant suppression');
                    supprimer.click();
                    return;
                }
                assert(statut.hidden,'Pas de chargement initial');
                assert(document.querySelector('.annexe-item').title==='Déposé par Louis Calu le 15/10/2026','Métadonnées réelles au survol');
                assert(document.querySelector('.btn-copier-chemin img').getAttribute('src').endsWith('/copy.png'),'Icône copier réutilisée');
                assert(!document.querySelector('.annexe-texte img'),'Pas d’icône devant le titre');
                const annexe=document.querySelector('.annexe-item');
                const copie=annexe.querySelector('.btn-copier-chemin');
                const supprimer=annexe.querySelector('.btn-supprimer-annexe');
                const feedback=annexe.querySelector('.copie-feedback');
                const titreAnnexe=annexe.querySelector('.annexe-texte');
                assert(copie.getBoundingClientRect().left-titreAnnexe.getBoundingClientRect().right<12,'Copier juste à côté du titre');
                assert(annexe.getBoundingClientRect().width<annexe.parentElement.clientWidth,'Fond limité au contenu');
                assert(supprimer.getBoundingClientRect().left>copie.getBoundingClientRect().left,'Supprimer à droite de copier');
                assert(feedback.getClientRects().length===0,'Aucune place réservée au feedback');
                const largeurTitre=annexe.querySelector('.annexe-texte').getBoundingClientRect().width;
                feedback.classList.add('show');
                assert(getComputedStyle(feedback).color==='rgb(0, 0, 0)','Copié en noir');
                assert(getComputedStyle(feedback).backgroundColor==='rgba(0, 0, 0, 0)','Copié sans fond');
                assert(feedback.getBoundingClientRect().top>=copie.getBoundingClientRect().bottom,'Feedback sous la ligne');
                assert(largeurTitre===annexe.querySelector('.annexe-texte').getBoundingClientRect().width,'Feedback sans réduire le titre');
                feedback.classList.remove('show');
                const largeurInitiale=annexe.parentElement.style.width;
                annexe.parentElement.style.width='240px';
                const titreInitial=titreAnnexe.textContent;
                titreAnnexe.textContent='annexe_avec_un_titre_tres_long_'.repeat(12)+'.pdf';
                assert(annexe.getBoundingClientRect().right<=annexe.parentElement.getBoundingClientRect().right+1,'Annexe longue contenue');
                assert(titreAnnexe.scrollWidth>titreAnnexe.clientWidth,'Titre annexe tronqué');
                titreAnnexe.textContent=titreInitial;annexe.parentElement.style.width=largeurInitiale;
                for(const largeur of [280,360,480]) {
                    for(const zone of document.querySelectorAll('[data-test-documents]')) {
                        zone.style.width=largeur+'px';
                        const limite=zone.getBoundingClientRect().right;
                        for(const pj of zone.querySelectorAll('.pj_champ, .champ-dn-apres-depot')) {
                            assert(pj.getBoundingClientRect().right<=limite+1,'Bloc PJ contenu à '+largeur+'px');
                        }
                        for(const bloc of zone.querySelectorAll('.document-avec-apercu')) {
                            assert(bloc.getBoundingClientRect().right<=limite+1,'Document contenu à '+largeur+'px');
                            const titre=bloc.querySelector('.document-titre');
                            assert(titre.clientWidth<titre.scrollWidth,'Titre long tronqué à '+largeur+'px');
                            for(const action of bloc.querySelectorAll('button, .document-download-link')) {
                                assert(action.getBoundingClientRect().right<=limite+1,'Action accessible à '+largeur+'px');
                            }
                        }
                    }
                }
                const note=document.querySelector('.form-note');
                note.addEventListener('submit',event=>event.preventDefault());
                note.requestSubmit();await wait();
                assert(!attente.hidden && attente.parentElement===document.body,'Note textuelle : chargement plein écran');
                assert(attente.textContent.includes('Enregistrement de la note'),'Chargement de la note sans annonce de succès prématurée');
                assert(getComputedStyle(attente).position==='fixed','Chargement au-dessus de la page');
                window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}));
                const annuler=event=>event.preventDefault();
                note.addEventListener('submit',annuler,{capture:true});
                note.requestSubmit();assert(attente.hidden,'Pas de chargement pour une soumission annulée');
                note.removeEventListener('submit',annuler,{capture:true});
                choisir('nouveau.pdf');await wait();
                assert(!attente.hidden && input.disabled,'Chargement visible pendant toute la requête');
                assert(getComputedStyle(loader).animationName==='notification-agents-rotation','Même spinner que le retour en instruction');
                assert(form.getAttribute('aria-busy')==='true','État occupé annoncé');
                assert(donnees.get('annexe').name==='nouveau.pdf','Fichier présent dans le POST malgré le verrouillage');
                input.dispatchEvent(new Event('change'));assert(appels===1,'Pas de double envoi');
                terminer(new Response(JSON.stringify({success:false,error:'Écriture NAS impossible'}), {status:500,headers:{'Content-Type':'application/json'}}));
                await wait();
                assert(attente.hidden&&!input.disabled&&input.value==='','Erreur : loader arrêté et nouvelle tentative possible');
                assert(statut.classList.contains('is-error')&&statut.textContent.includes('Écriture NAS impossible'),'Erreur serveur visible');
                choisir('existant.pdf');await wait();
                assert(appels===1&&input.value==='','Remplacement annulé sans upload');
                choisir('nouveau.pdf');await wait();
                assert(appels===2&&!attente.hidden,'Retentative avec loader');
                window.scrollTo(0,450);
                sessionStorage.setItem('scroll-attendu',String(window.scrollY));
                sessionStorage.setItem('upload-termine','1');
                window.addEventListener('pagehide',()=>{
                    sessionStorage.setItem('chargement-jusqua-navigation',!attente.hidden && input.disabled ? 'oui':'non');
                });
                terminer(new Response(JSON.stringify({success:true}),{status:201,headers:{'Content-Type':'application/json'}}));
            } catch(erreur) { sortie.textContent='ANNEXES_NOTES_ERREUR: '+erreur.message; }
        });
        """
        html = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
        <link rel="stylesheet" href="/static/instruction/css/dossier.css">
        <link rel="stylesheet" href="/static/instruction/css/instruction_dossier.css">
        <link rel="stylesheet" href="/static/instruction/css/dossier_manif_sportive.css">
        <script src="/static/instruction/js/dossier_commun.js"></script>
        <script>{script}</script></head><body>
        <script type="application/json" id="emplacements-existants">["Dossier/Annexes/existant.pdf"]</script>
        <div class="groupe-instructeur-info notes_instructeurs">{bloc}
        <form class="form-note" method="post" action="/note/"><textarea name="note">Une note</textarea><button type="submit">Enregistrer</button></form></div>
        <div data-test-documents>{document}</div>
        <div data-test-documents class="champs"><div class="pj_champ"><p><strong>Intitulé du champ de pièce jointe particulièrement long</strong> : {document}</p></div></div>
        <div data-test-documents class="champs"><div class="champ-dn-apres-depot champ-dn-apres-depot-compact"><div class="pj_champ"><p><strong>Pièces justificatives ajoutées ou modifiées après le dépôt</strong> : {document}</p></div></div></div>
        <div data-test-documents><div class="doc-download-row">{document}</div></div>
        <div style="height:2400px" aria-hidden="true"></div>
        </body></html>"""

        suppressions = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                suppressions.append(parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode()))
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == "/":
                    data, content_type = html.encode("utf-8"), "text/html; charset=utf-8"
                elif path.startswith("/static/instruction/"):
                    fichier = src / "instruction/static/instruction" / path.removeprefix("/static/instruction/")
                    data = fichier.read_bytes()
                    content_type = {".js": "application/javascript", ".css": "text/css", ".svg": "image/svg+xml"}.get(fichier.suffix, "image/png")
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.end_headers()
                self.wfile.write(data)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="agida-notes-") as profile:
                resultat = subprocess.run([
                    str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run", "--disable-background-networking",
                    f"--user-data-dir={profile}", "--window-size=540,900", "--virtual-time-budget=5000", "--dump-dom",
                    f"http://127.0.0.1:{server.server_port}/",
                ], capture_output=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
                dom = resultat.stdout.decode("utf-8", errors="replace")
                self.assertTrue('>ANNEXES_NOTES_OK</pre>' in dom, dom[-4000:] or resultat.stderr.decode("utf-8", errors="replace")[-2000:])
                self.assertEqual(len(suppressions), 1, "Une seule suppression après confirmation, même en cas de double clic.")
                self.assertEqual(suppressions[0]["document_id"], ["3"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
