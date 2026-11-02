"""Rappel et destinataires DM : navigateur local, sans aucun envoi de mail."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import tempfile
from threading import Thread
from types import SimpleNamespace as NS
from unittest import skipUnless

from django.template.loader import render_to_string
from django.test import SimpleTestCase

from instruction.utils.utilisateurs_utils import get_destinataires_relance_dm


SRC = Path(__file__).resolve().parents[2]
CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


class RelancesDMInterfaceTests(SimpleTestCase):
    @skipUnless(CHROME.exists(), "Chrome headless indisponible.")
    def test_rappel_et_modification_des_destinataires_sur_petit_et_grand_ecran(self):
        css = "\n".join((SRC / "instruction/static/instruction/css" / fichier).read_text(encoding="utf-8")
                        for fichier in ("dossier.css", "dossier_manif_sportive_sans_ds.css"))
        js = (SRC / "instruction/static/instruction/js/mail_relance.js").read_text(encoding="utf-8")
        pages = {}
        for nom, structure, coordinateur in (
            ("deux", "structure@example.test", "securite@example.test"),
            ("coordinateur", None, "securite@example.test"),
            ("doublon", "structure@example.test", "STRUCTURE@example.test"),
            ("aucun", None, None),
        ):
            dm = NS(email_structure=structure, email_coordinateur_securite=coordinateur,
                    numero_telephone="06 92 12 34 56",
                    archive=False, id_etape=NS(etape="En réception"))
            emails = get_destinataires_relance_dm(dm)
            contexte = {"doss_manif_sportive": dm, "emails_relance_organisateur": emails,
                        "instructeurs_dm_affectes_ids": {7, 8}, "instructeur_connecte": NS(id=7)}
            rappel = render_to_string("instruction/refacto/dm_relance_information.html", contexte)
            formulaire = render_to_string("instruction/refacto/dm_relance_destinataires.html", contexte)
            verification = """
            window.addEventListener('load',()=>{
                const sortie=document.createElement('pre');document.body.append(sortie);
                const assert=(ok,message)=>{if(!ok)throw new Error(message);};
                try {
                    const attendus=EMAILS;
                    const emails=()=>[...document.querySelectorAll('.hidden-email-relance')].map(input=>input.value);
                    assert(JSON.stringify(emails())===JSON.stringify(attendus),'Destinataires initiaux');
                    const rappel=document.querySelector('.dm-relance-information');
                    assert(rappel&&rappel.textContent.includes('Si la dernière relance'),'Rappel de relance affiché');
                    assert(rappel.textContent.includes('Aucune adresse')===(attendus.length===0),'Absence de mail signalée seulement si nécessaire');
                    assert(rappel.textContent.includes('contacter l’organisation par téléphone.')===(attendus.length===0),'Contact téléphonique proposé uniquement sans mail');
                    assert(rappel.getBoundingClientRect().right<=innerWidth,'Rappel sans débordement sur petit écran');
                    afficherFormulaireRelanceDemandeur();
                    const zone=document.getElementById('formulaire-relance-demandeur');
                    assert(getComputedStyle(zone).display!=='none','Ouverture du formulaire');
                    const input=document.getElementById('nouvel-email-relance');
                    if(attendus.length){
                        input.value=attendus[0].toUpperCase();ajouterEmailRelance();
                        assert(emails().length===attendus.length,'Doublon ignoré sans tenir compte de la casse');
                        retirerEmailRelance(document.querySelector('.chip button'));
                        assert(JSON.stringify(emails())===JSON.stringify(attendus.slice(1)),'Retrait limité au destinataire choisi');
                    }
                    input.value='ajout@example.test';ajouterEmailRelance();
                    assert(emails().includes('ajout@example.test'),'Ajout manuel conservé');
                    assert(JSON.stringify(emails())===JSON.stringify([...document.querySelectorAll('.chip')].map(chip=>chip.dataset.email)),'Adresses affichées et POST identiques');
                    let envois=0;document.querySelector('form').submit=()=>{envois++;};
                    window.confirm=()=>false;confirmerRelanceDemandeur();
                    assert(envois===0,'Aucun envoi de mail pendant le test');
                    fermerFormulaireRelanceDemandeur();
                    assert(!zone.classList.contains('show'),'Fermeture du formulaire');
                    sortie.textContent='RELANCES_DM_OK';
                } catch(error) {sortie.textContent='RELANCES_DM_ERREUR: '+error.message;}
            });
            """.replace("EMAILS", json.dumps(emails))
            pages["/" + nom] = (
                '<!doctype html><html><head><meta charset="utf-8">'
                f'<style>{css}body{{margin:0;padding:1rem;box-sizing:border-box}}</style>'
                f'<script>{js}\n{verification}</script></head><body>{rappel}'
                f'<div id="formulaire-relance-demandeur" class="zone-complement zone-relance-demandeur">'
                f'<form class="form-relance-demandeur">{formulaire}</form></div></body></html>'
            ).encode("utf-8")

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(pages.get(self.path, b""))

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for nom in ("deux", "coordinateur", "doublon", "aucun"):
                for largeur in (390, 1400):
                    with self.subTest(cas=nom, largeur=largeur), tempfile.TemporaryDirectory(prefix="agida-relances-") as profil:
                        resultat = subprocess.run([
                            str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run", "--disable-background-networking",
                            f"--user-data-dir={profil}", f"--window-size={largeur},1000", "--virtual-time-budget=1200", "--dump-dom",
                            f"http://127.0.0.1:{server.server_port}/{nom}",
                        ], capture_output=True, timeout=45, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                        dom = resultat.stdout.decode("utf-8", errors="replace")
                        self.assertIn(">RELANCES_DM_OK</pre>", dom, dom[dom.rfind("<pre>"):] or resultat.stderr.decode("utf-8", errors="replace")[-1500:])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
