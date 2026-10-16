"""Affichage responsive des avis existants, sans base, API, mail ni NAS."""
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


CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


@skipUnless(CHROME.exists(), "Chrome headless indisponible.")
class AvisExistantInterfaceTests(SimpleTestCase):
    def test_libelles_radios_et_selects_sur_petits_et_grands_ecrans(self):
        src = Path(__file__).resolve().parents[2]
        instructeur = SimpleNamespace(id=10, email="adresse.mail.extremement.longue." * 10 + "@exemple.test",
            id_agent_autorisations=SimpleNamespace(nom="CALU", prenom="Louis"))
        page = render_to_string("instruction/instruction_dossier_ajouter_avis_existant.html", {
            "dossier": SimpleNamespace(numero=30655697, id_demarche=SimpleNamespace(type="Travaux")),
            "natures": [SimpleNamespace(id=1, nature="Demande à une instance"), SimpleNamespace(id=2, nature="Consultation en interne")],
            "thematiques": [SimpleNamespace(id=3, thematique="Travaux")],
            "tous_les_instructeurs": [instructeur], "instructeurs": [instructeur],
            "contacts_externes": [SimpleNamespace(id=20, nom="COLLIN", prenom="Gérard", email=instructeur.email)],
            "tous_les_experts": [instructeur], "avis_list": None,
        })
        page = page.replace("</body>", f"<script>{self.script()}</script></body>").encode("utf-8")

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == "/":
                    data, mime = page, "text/html; charset=utf-8"
                elif path.startswith("/static/instruction/"):
                    fichier = src / "instruction/static/instruction" / path.removeprefix("/static/instruction/")
                    if not fichier.is_file():
                        self.send_error(404)
                        return
                    data = fichier.read_bytes()
                    mime = {".js": "application/javascript", ".css": "text/css"}.get(fichier.suffix, "image/png")
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
            for largeur in (360, 540, 1440):
                with self.subTest(largeur=largeur), tempfile.TemporaryDirectory(prefix="agida-avis-existant-") as profile:
                    resultat = subprocess.run([
                        str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run", "--disable-background-networking",
                        f"--user-data-dir={profile}", f"--window-size={largeur},1000", "--virtual-time-budget=2000", "--dump-dom",
                        f"http://127.0.0.1:{server.server_port}/#{largeur}",
                    ], capture_output=True, timeout=45, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    dom = resultat.stdout.decode("utf-8", errors="replace")
                    self.assertIn(">AVIS_EXISTANT_OK</pre>", dom, dom[-2500:])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    @staticmethod
    def script():
        return """
        window.addEventListener('load',()=>{
            const sortie=document.createElement('pre');document.body.append(sortie);
            const assert=(ok,message)=>{if(!ok)throw new Error(message);};
            const q=selecteur=>document.querySelector(selecteur);
            const choisir=(selecteur,valeur)=>{q(selecteur).value=valeur;q(selecteur).dispatchEvent(new Event('change'));};
            try {
                // Chrome desktop impose parfois une largeur minimale : contraindre aussi le conteneur.
                const largeur=Number(location.hash.slice(1));
                if(largeur<innerWidth)q('.avis-page-container').style.width=largeur+'px';
                choisir('#type_avis','avis_hors_application');
                choisir('#demandeur_avis','10');
                const contenu=q('.form_ajout_demande_avis');
                const cadre=contenu.getBoundingClientRect();
                const contenuDansCadre=selecteur=>{
                    document.querySelectorAll(selecteur).forEach(el=>{
                        if(!el.getClientRects().length)return;
                        const rect=el.getBoundingClientRect();
                        assert(rect.left>=cadre.left&&rect.right<=cadre.right+1,'Débordement : '+(el.id||el.name||el.className));
                    });
                };
                contenuDansCadre('.attribut_avis select, .attribut_avis input, .attribut_avis textarea, .radio-group label');
                const titre=q('.avis-reponse-label');
                assert(titre.getBoundingClientRect().height<30,'Réponse de l’avis sur une seule ligne');
                const demandeur=q('label[for="demandeur_avis"]');
                assert(demandeur.getBoundingClientRect().height<(largeur<540?45:30),'Libellé instructeur non écrasé par le select');
                document.querySelectorAll('.radio-group label').forEach(label=>{
                    const radio=label.querySelector('input');
                    const rect=radio.getBoundingClientRect();
                    const texte=[...label.childNodes].find(node=>node.nodeType===Node.TEXT_NODE&&node.textContent.trim());
                    const range=document.createRange();range.selectNodeContents(texte);
                    const lignes=[...range.getClientRects()].filter(r=>r.width>0);
                    assert(lignes.length===1,'Libellé radio sur une seule ligne');
                    assert(Math.abs((rect.top+rect.bottom)/2-(lignes[0].top+lignes[0].bottom)/2)<5,'Radio alignée avec son libellé');
                    label.click();
                    assert(q('input[name=reponse]:checked')===radio,'Choix radio toujours fonctionnel');
                });
                assert(new FormData(q('#form-avis')).get('reponse')==='absence_avis_en_etat','Valeurs transmises inchangées');
                choisir('#nature','1');choisir('#expert_externe','20');
                assert(getComputedStyle(q('#bloc_expert_externe')).display==='flex','Expert externe en ligne flexible');
                contenuDansCadre('.attribut_avis select');
                choisir('#nature','2');choisir('#expert_interne','10');
                assert(getComputedStyle(q('#bloc_expert_interne')).display==='flex','Expert interne en ligne flexible');
                contenuDansCadre('.attribut_avis select');
                choisir('#type_avis','avis_sur_application');
                contenuDansCadre('.form_avis_dans_appli input, .form_avis_dans_appli select, .form_avis_dans_appli button');
                sortie.textContent='AVIS_EXISTANT_OK';
            } catch(erreur) {sortie.textContent='ECHEC: '+erreur.message;}
        });
        """
