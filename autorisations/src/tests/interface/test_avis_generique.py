"""Affichage du numéro réservé et champs conditionnels, dans Chrome local."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import tempfile
from threading import Thread
from types import SimpleNamespace
from unittest import skipUnless
from urllib.parse import urlsplit

from django.template.loader import render_to_string
from django.test import SimpleTestCase
from instruction.utils.avis_formulaires import configuration_standard


CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


@skipUnless(CHROME.exists(), "Chrome headless indisponible.")
class AvisGeneriqueInterfaceTests(SimpleTestCase):
    def test_numero_et_formulaire_generique(self):
        src = Path(__file__).resolve().parents[2]
        reservation = SimpleNamespace(id="af2cd0a5-dacd-4488-958d-bb83db1cc2bf", numero=1051)
        html = render_to_string("instruction/avis_nouvelle_demande_generique.html", {
            "reservation": reservation,
            "avis_formulaire_configuration": {"champs": configuration_standard("generique"), "variables": {"numero_avis": 1051}},
            "natures": [SimpleNamespace(id=1, nature="Demande à une instance"), SimpleNamespace(id=2, nature="Consultation en interne")],
            "demarches": [SimpleNamespace(id=3, type="Travaux")], "thematiques": [SimpleNamespace(id=4, thematique="Travaux")],
            "instructeurs": [SimpleNamespace(id=8, email="interne@example.test")],
            "contacts_externes": [SimpleNamespace(id=9, nom=None, prenom=None, raison_sociale="Conseil Scientifique", organisation=None, email="cs@example.test")],
            "csrf_token": "test",
        })
        script = """
        window.addEventListener('load',()=>{
            const resultat=document.createElement('pre');document.body.append(resultat);
            const q=s=>document.querySelector(s);
            const assert=(ok,msg)=>{if(!ok)throw new Error(msg);};
            const choisir=(s,v)=>{q(s).value=v;q(s).dispatchEvent(new Event('change'));};
            try {
                assert(q('h1').textContent.includes('1051'),'Numéro dans le titre');
                assert(q('[name=reservation]').value==='af2cd0a5-dacd-4488-958d-bb83db1cc2bf','Réservation conservée à la soumission');
                choisir('#nature','1');choisir('#expert_externe','9');
                assert(!q('#bloc_pj_demande_avis').hidden&&!q('#bloc_pj_rapport_cs').hidden,'Pièces instance visibles');
                assert(q('.avis-generique-rappel-numero').textContent.includes('1051'),'Rappel du numéro réservé');
                assert(getComputedStyle(q('.avis-generique-rappel-numero')).fontStyle==='italic','Rappel en italique');
                assert(getComputedStyle(q('.avis-generique-rappel-numero')).color==='rgb(139, 30, 30)','Rappel rouge foncé');
                const labelProjet=q('#label_pj_demande_avis').getBoundingClientRect();
                const fichierProjet=q('#pj_demande_avis').getBoundingClientRect();
                assert(Math.abs((labelProjet.top+labelProjet.bottom-fichierProjet.top-fichierProjet.bottom)/2)<1,'Sélecteur générique aligné sur le libellé');
                assert(q('.avis-generique-rappel-numero').getBoundingClientRect().top>=Math.max(labelProjet.bottom,fichierProjet.bottom),'Rappel générique sous la ligne du champ');
                q('.form_nouvelle_demande_generique').style.width='280px';
                assert(q('.avis-generique-rappel-numero').getBoundingClientRect().top>=q('#pj_demande_avis').getBoundingClientRect().bottom,'Sur petite largeur le rappel reste sous le sélecteur');
                q('.form_nouvelle_demande_generique').style.width='';
                assert(q('#pj_demande_avis').required,'Projet instance obligatoire');
                assert(q('#pj_projet_acte').required,'Projet d’acte obligatoire aussi en générique');
                const champs=Array.from(document.querySelectorAll('.attribut_avis')).filter(el=>el.getClientRects().length).map(el=>el.querySelector('select,input,textarea').id);
                assert(champs.join(',')==='nature,expert_externe,destinataire,demarche,thematique,note_demandeur,pj_demande_avis,pj_projet_acte,pj_rapport_cs,pj_lie_avis,formulation_avis','Ordre identique à Consultation avec Type avant Thématique');
                choisir('#nature','2');choisir('#expert_interne','8');
                assert(q('#bloc_pj_demande_avis').hidden&&q('#bloc_pj_rapport_cs').hidden,'Pièces instance masquées en interne');
                assert(q('#pj_demande_avis').disabled&&q('#pj_rapport_cs').disabled,'Pièces masquées non transmises');
                assert(q('#label_pj_lie_avis').textContent==='Pièces jointes à transmettre :','Libellé interne');
                choisir('#demarche','3');choisir('#thematique','4');
                const donnees=new FormData(q('#form-avis'));
                assert(!donnees.has('pj_demande_avis')&&!donnees.has('pj_rapport_cs'),'Aucune pièce instance dans le POST interne');
                assert(donnees.get('reservation')==='af2cd0a5-dacd-4488-958d-bb83db1cc2bf','Numéro réservé indépendant de la nature choisie');
                resultat.textContent='AVIS_GENERIQUE_OK';
            } catch(erreur) {resultat.textContent='AVIS_GENERIQUE_ERREUR: '+erreur.message;}
        });
        """
        html = html.replace("</body>", f"<script>{script}</script></body>")

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == "/":
                    data, mime = html.encode("utf-8"), "text/html; charset=utf-8"
                elif path.startswith("/static/instruction/"):
                    fichier = src / "instruction/static/instruction" / path.removeprefix("/static/instruction/")
                    if not fichier.is_file():
                        self.send_error(404)
                        return
                    data = fichier.read_bytes()
                    mime = {".js": "application/javascript", ".css": "text/css", ".svg": "image/svg+xml"}.get(fichier.suffix, "image/png")
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.end_headers()
                self.wfile.write(data)

        serveur = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=serveur.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="agida-avis-generique-") as profil:
                resultat = subprocess.run([
                    str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run", "--disable-background-networking",
                    f"--user-data-dir={profil}", "--window-size=1000,1000", "--virtual-time-budget=2000", "--dump-dom",
                    f"http://127.0.0.1:{serveur.server_port}/",
                ], capture_output=True, timeout=45, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                dom = resultat.stdout.decode("utf-8", errors="replace")
                self.assertIn(">AVIS_GENERIQUE_OK</pre>", dom, dom[-2500:])
        finally:
            serveur.shutdown()
            serveur.server_close()
            thread.join(timeout=2)
