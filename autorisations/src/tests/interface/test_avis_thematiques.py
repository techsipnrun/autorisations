"""Gestion du catalogue en navigateur, serveur local simulé, aucune BDD."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import tempfile
from threading import Thread
from unittest import skipUnless

from django.template.loader import render_to_string
from django.test import SimpleTestCase


CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


@skipUnless(CHROME.exists(), "Chrome headless indisponible.")
class CatalogueAvisInterfaceTests(SimpleTestCase):
    def test_filtres_edition_creation_erreur_et_responsive(self):
        src = Path(__file__).resolve().parents[2] / "instruction/static/instruction"
        contenu = render_to_string("instruction/refacto/back_office_avis_thematiques.html", {"csrf_token": "test"})
        categories = [{"valeur": "", "libelle": "Non rattachée"}, {"valeur": "Autre", "libelle": "Toutes les démarches"},
                      {"valeur": "Activités commerciales", "libelle": "Activités commerciales"}]
        script = """
        window.addEventListener('load',async()=>{
            const sortie=document.createElement('pre');document.body.append(sortie);
            const q=s=>document.querySelector(s);
            const assert=(ok,msg)=>{if(!ok)throw new Error(msg);};
            const attendre=async(p)=>{for(let i=0;i<80;i++){if(p())return;await new Promise(r=>setTimeout(r,25));}throw new Error('Attente trop longue');};
            try {
                await attendre(()=>q('[data-theme-id="1"]'));
                const largeurListe=q('[data-theme-liste]').getBoundingClientRect().width;
                assert(largeurListe<=64*parseFloat(getComputedStyle(document.documentElement).fontSize)+1,'Largeur liste plafonnée');
                if(innerWidth>=1400)assert(largeurListe<q('.back-office-panel').getBoundingClientRect().width-16,'Liste non étirée sur grand écran');
                const summary=q('.bo-avis-theme-add > summary');
                assert(summary.getBoundingClientRect().width<q('.back-office-panel').getBoundingClientRect().width-16,'Action ajouter compacte');
                assert(getComputedStyle(summary,'::after').content==='none','Pas de deuxième icône de dépliage');
                const row=q('[data-theme-id="1"]');
                assert(row.elements.demarche.value==='Activités commerciales','Rattachement de la table chargé');
                row.elements.demarche.value='Autre';row.elements.demarche.dispatchEvent(new Event('input',{bubbles:true}));
                assert(row.classList.contains('is-dirty'),'Modification signalée');
                row.querySelector('button').click();
                await attendre(()=>row.querySelector('.is-error'));
                assert(row.elements.demarche.value==='Autre','Erreur conserve la sélection');
                row.querySelector('button').click();
                await attendre(()=>row.querySelector('[data-theme-message]').textContent.startsWith('Thématique enregistrée'));
                assert(!row.classList.contains('is-dirty'),'Modification confirmée');
                const filtre=q('[data-theme-filtre]');filtre.value='Activités commerciales';filtre.dispatchEvent(new Event('change'));
                assert(row.hidden,'Filtrage selon rattachement modifié');
                filtre.value='__tous__';filtre.dispatchEvent(new Event('change'));
                const recherche=q('[data-theme-recherche]');recherche.value='inexistant';recherche.dispatchEvent(new Event('input'));
                assert(row.hidden,'Recherche par libellé');recherche.value='';recherche.dispatchEvent(new Event('input'));
                const ajout=q('[data-theme-ajout]');ajout.closest('details').open=true;
                assert(ajout.querySelector('button').getBoundingClientRect().width<150,'Bouton Ajouter non étiré');
                ajout.elements.thematique.value='Nouveau thème';ajout.elements.demarche.value='Activités commerciales';
                ajout.querySelector('button').click();
                await attendre(()=>q('[data-theme-id="2"]'));
                assert(q('[data-theme-id="2"]').elements.thematique.value==='Nouveau thème','Création ajoutée au catalogue');
                const limite=q('.back-office-panel').getBoundingClientRect().right;
                document.querySelectorAll('input,select,button').forEach(el=>{
                    if(el.getClientRects().length)assert(el.getBoundingClientRect().right<=limite+1,'Contrôle contenu sur petit écran');
                });
                sortie.textContent='THEMATIQUES_AVIS_OK';
            }catch(e){sortie.textContent='ECHEC: '+e.message;}
        });
        """
        page = f'''<!doctype html><html><head><meta charset="utf-8">
        <link rel="stylesheet" href="/static/instruction/css/back_office.css">
        <link rel="stylesheet" href="/static/instruction/css/back_office_avis.css">
        <script src="/static/instruction/js/back_office_avis_thematiques.js"></script></head>
        <body><div class="back-office-layout"><aside class="back-office-sidebar"></aside><main class="back-office-content"><section class="back-office-panel" data-panel="avis-thematiques">{contenu}</section></main></div><script>{script}</script></body></html>'''.encode()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def repondre(self, data, mime="application/json", status=200):
                self.send_response(status);self.send_header("Content-Type", mime);self.end_headers();self.wfile.write(data)

            def do_GET(self):
                if self.path == "/":
                    self.repondre(page, "text/html; charset=utf-8")
                elif self.path.startswith("/static/instruction/"):
                    fichier = src / self.path.removeprefix("/static/instruction/")
                    self.repondre(fichier.read_bytes(), "text/css" if fichier.suffix == ".css" else "application/javascript")
                elif self.path == "/back-office/avis/thematiques/":
                    self.server.tentative = 0
                    self.repondre(json.dumps({"categories": categories, "thematiques": [{"id": 1, "thematique": "Artisanat", "demarche": "Activités commerciales"}]}).encode())
                else:
                    self.send_error(404)

            def do_POST(self):
                donnees = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                self.server.tentative += 1
                if self.server.tentative == 1:
                    self.repondre(json.dumps({"error": "Erreur simulée"}).encode(), status=500)
                else:
                    donnees["id"] = donnees["id"] or 2
                    self.repondre(json.dumps({"success": True, "thematique": donnees}).encode())

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True);thread.start()
        try:
            for largeur in (540, 1600):
                with self.subTest(largeur=largeur), tempfile.TemporaryDirectory(prefix="agida-themes-") as profil:
                    resultat = subprocess.run([str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run", "--disable-background-networking",
                        f"--user-data-dir={profil}", f"--window-size={largeur},1000", "--virtual-time-budget=5000", "--dump-dom", f"http://127.0.0.1:{server.server_port}/#avis/thematiques"],
                        capture_output=True, timeout=45, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    dom = resultat.stdout.decode("utf-8", errors="replace")
                    self.assertIn(">THEMATIQUES_AVIS_OK</pre>", dom, dom[-1800:])
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2)
