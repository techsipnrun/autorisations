"""Regroupement visuel des actions DN, avec les templates et fonctions réels."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import re
import subprocess
import tempfile
from threading import Thread
from types import SimpleNamespace
from unittest import skipUnless
from urllib.parse import urlsplit

from django.template import Context, Template
from django.test import SimpleTestCase


SRC = Path(__file__).resolve().parents[2]
CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
ACTIONS = [
    "Classer comme annulé",
    "Archiver le dossier comme refusé",
    "Archiver le dossier comme accepté",
    "Archiver le dossier comme non soumis à autorisation",
]


def rendre_menu(nom="instruction_dossier", present=True, actions=None, etape="En instruction", autorise=True):
    source = (SRC / f"instruction/templates/instruction/{nom}.html").read_text(encoding="utf-8")
    fragment = '<div class="etat-badge-menu-dropdown">' + source.split(
        '<div class="etat-badge-menu-dropdown">', 1)[1].split("<!-- Téléchargement PDF -->", 1)[0]
    utilisateur = SimpleNamespace(is_authenticated=True, is_superuser=autorise, email="",
                                 _instruction_group_names_cache=set(), _instruction_instructeur_cache=None)
    contexte = {
        "request": SimpleNamespace(user=utilisateur), "peut_changer_etape": autorise,
        "dossier": SimpleNamespace(id_ds="Dossier-test", present_sur_ds=present,
                                   id_etat_dossier=SimpleNamespace(nom="accepte")),
        "etape_actuelle": SimpleNamespace(etape=etape), "etape_dossier": etape,
        "actions_possibles": ACTIONS if actions is None else actions, "csrf_token": "test",
    }
    return Template("{% load group_tags custom_filters %}" + fragment).render(Context(contexte)), source


def fonction_js(source, nom):
    debut = source.index(f"function {nom}(")
    ouverture = source.index("{", debut)
    profondeur = 1
    fin = ouverture + 1
    while profondeur:
        profondeur += (source[fin] == "{") - (source[fin] == "}")
        fin += 1
    return source[debut:fin]


class MenuArchivageTests(SimpleTestCase):
    def test_perimetre_dn_et_permissions_conserves(self):
        for nom in ("instruction_dossier", "preinstruction_dossier"):
            with self.subTest(template=nom):
                en_ligne, _ = rendre_menu(nom)
                self.assertIn("data-archivage-dn", en_ligne)
                self.assertEqual(en_ligne.count("data-archive-action="), 4)
                hors_ligne, _ = rendre_menu(nom, present=False)
                self.assertNotIn("data-archivage-dn", hors_ligne)
                self.assertEqual(hors_ligne.count('name="csrfmiddlewaretoken"'), 4)
                refuse, _ = rendre_menu(nom, autorise=False)
                self.assertNotIn('id="etapeMenuContent"', refuse)
        dm = (SRC / "instruction/templates/instruction/dossier_manif_sportive_sans_ds.html").read_text(encoding="utf-8")
        self.assertNotIn("data-archivage-dn", dm)

    def test_regroupement_base_sur_les_boutons_effectivement_rendus(self):
        raa, _ = rendre_menu(actions=ACTIONS[1:3], etape="À publier au RAA")
        self.assertEqual(raa.count("data-archive-action="), 1)
        unique, _ = rendre_menu(actions=ACTIONS[:1])
        self.assertEqual(unique.count("data-archive-action="), 1)
        vide, _ = rendre_menu(actions=[])
        self.assertNotIn("data-archive-action=", vide)

    @skipUnless(CHROME.exists(), "Chrome headless indisponible.")
    def test_survol_clic_formulaires_et_petits_ecrans(self):
        css = (SRC / "instruction/static/instruction/css/dossier.css").read_text(encoding="utf-8")
        commun = (SRC / "instruction/static/instruction/js/dossier_commun.js").read_text(encoding="utf-8")
        menu_js = commun.split("// Réassociation manuelle", 1)[0]
        pages = {}
        for cas, template, present, actions, etape in (
            ("instruction", "instruction_dossier", True, ACTIONS, "En instruction"),
            ("preinstruction", "preinstruction_dossier", True, ACTIONS, "En pré-instruction"),
            ("deux", "instruction_dossier", True, ACTIONS[:2], "En instruction"),
            ("hors-dn", "instruction_dossier", False, ACTIONS, "En instruction"),
            ("unique", "instruction_dossier", True, ACTIONS[:1], "En instruction"),
            ("raa", "instruction_dossier", True, ACTIONS[1:3], "À publier au RAA"),
        ):
            menu, source = rendre_menu(template, present, actions, etape)
            noms = ["masquerToutesZonesComplementaires", "fermerMenuEtape", "afficherFormulaireClassement",
                    "afficherFormulaireAnnulation", "afficherFormulaireAcceptationDirecte",
                    "afficherFormulaireRefusDirect" if template == "preinstruction_dossier" else "afficherFormulaireRefus"]
            fonctions = "\n".join(fonction_js(source, nom) for nom in noms)
            zones = set(re.findall(r'getElementById\("(formulaire-[^"]+)"\)\.classList.add', fonctions))
            formulaires = "".join(f'<div id="{zone}" class="zone-complement"></div>' for zone in zones)
            test = """
            const mediaNatif=window.matchMedia.bind(window);
            window.matchMedia=query=>query.includes('hover: hover')?{matches:true}:mediaNatif(query);
            window.confirm=()=>false;
            window.addEventListener('load',()=>{
                const sortie=document.createElement('pre');document.body.append(sortie);
                const assert=(ok,message)=>{if(!ok)throw new Error(message);};
                try {
                    const menu=document.getElementById('etapeMenuContent');
                    const groupe=menu.querySelector('.etape-archives');
                    const attendu=['instruction','preinstruction','deux'].includes(CAS);
                    assert(Boolean(groupe)===attendu,'Périmètre et seuil de deux boutons');
                    assert(noeudsAvant.every(noeud=>menu.contains(noeud)),'Conservation des vrais noeuds');
                    assert(noeudsAvant.every((noeud,i)=>noeud.outerHTML===htmlAvant[i]),'Handlers et champs inchangés');
                    document.getElementById('etapeMenuToggle').click();
                    if(!attendu) {
                        assert(noeudsAvant.every(noeud=>noeud.parentElement===menu),'Actions exclues inchangées');
                        document.body.click();
                        assert(!menu.classList.contains('show'),'Clic extérieur ferme le menu');
                    } else {
                        const bouton=groupe.querySelector('.etape-archives-trigger');
                        const panneau=groupe.querySelector('.etape-archives-panel');
                        const ordre=['annule','refuse','accepte','non_soumis'].filter(action=>noeudsAvant.some(n=>n.dataset.archiveAction===action));
                        assert([...panneau.children].map(n=>n.dataset.archiveAction).join(',')===ordre.join(','),'Ordre des actions disponibles');
                        assert(menu.querySelectorAll('[data-archive-action]').length===noeudsAvant.length,'Aucun doublon');
                        const petit=innerWidth<=760;
                        groupe.dispatchEvent(new PointerEvent('pointerenter',{pointerType:'mouse'}));
                        assert(panneau.hidden===petit,'Survol sur grand écran seulement');
                        if(!petit) {
                            const ancre=groupe.getBoundingClientRect(), rect=panneau.getBoundingClientRect();
                            if(location.search.includes('droite')) {
                                assert(groupe.classList.contains('ouvre-gauche')&&rect.right<=ancre.left+1,'Ouverture à gauche si nécessaire');
                            } else assert(rect.left>=ancre.right-1,'Ouverture latérale à droite');
                            assert(rect.right<=document.documentElement.clientWidth+1&&rect.left>=0,'Panneau contenu dans la fenêtre');
                            groupe.dispatchEvent(new PointerEvent('pointerleave',{pointerType:'mouse'}));
                            assert(panneau.hidden,'Fermeture en quittant le groupe');
                        }
                        const avant=menu.offsetHeight;
                        bouton.click();
                        assert(!panneau.hidden&&bouton.getAttribute('aria-expanded')==='true','Ouverture au clic sans fermer le menu principal');
                        if(petit) {
                            assert(groupe.classList.contains('ouvre-dessous'),'Sous-menu déplié sous le bouton');
                            assert(menu.offsetHeight>avant,'Place prise dans le menu sur petit écran');
                            const wrapper=menu.closest('.etat-badge-menu-dropdown');
                            assert(parseFloat(wrapper.style.marginBottom)>=menu.offsetHeight,'Marge recalculée');
                        }
                        bouton.click();assert(panneau.hidden,'Fermeture au second clic');
                        const cibles={
                            annule:'formulaire-annulation',
                            refuse:CAS==='preinstruction'?'formulaire-refus-direct':'formulaire-refus',
                            accepte:'formulaire-acceptation-directe',
                            non_soumis:CAS==='preinstruction'?'formulaire-classement-dn':'formulaire-classement',
                        };
                        for(const [action,cible] of Object.entries(cibles)) {
                            if(!panneau.querySelector('[data-archive-action="'+action+'"]'))continue;
                            if(!menu.classList.contains('show'))document.getElementById('etapeMenuToggle').click();
                            bouton.click();
                            panneau.querySelector('[data-archive-action="'+action+'"]').click();
                            assert(document.getElementById(cible).classList.contains('show'),'Formulaire actuel ouvert : '+action);
                            assert(!menu.classList.contains('show')&&panneau.hidden,'Fermeture complète après action');
                        }
                        document.getElementById('etapeMenuToggle').click();bouton.click();
                        document.body.click();
                        assert(!menu.classList.contains('show')&&panneau.hidden,'Clic extérieur ferme les deux niveaux');
                    }
                    sortie.textContent='MENU_ARCHIVAGE_OK';
                } catch(erreur) {sortie.textContent='MENU_ARCHIVAGE_ERREUR: '+erreur.message;}
            });
            """.replace("CAS", json.dumps(cas))
            pages["/" + cas] = (
                '<!doctype html><html><head><meta charset="utf-8">'
                f'<style>{css}body{{margin:16px}}body.droite{{margin-left:calc(100vw - 360px)}}</style>'
                f'<script>{test}</script><script src="/menu.js" defer></script></head>'
                f'<body>{menu}{formulaires}<script>{fonctions}\n'
                "if(location.search.includes('droite'))document.body.classList.add('droite');"
                "const noeudsAvant=[...document.querySelectorAll('[data-archive-action]')];"
                "const htmlAvant=noeudsAvant.map(noeud=>noeud.outerHTML);</script></body></html>"
            ).encode("utf-8")

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                chemin = urlsplit(self.path).path
                contenu = menu_js.encode("utf-8") if chemin == "/menu.js" else pages.get(chemin, b"")
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript; charset=utf-8" if chemin == "/menu.js" else "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(contenu)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for cas, largeur in (
                ("instruction", 1400), ("instruction?droite", 1400),
                ("preinstruction", 1400), ("instruction", 540), ("preinstruction", 540),
                ("deux", 1400),
                ("hors-dn", 1400), ("unique", 1400), ("raa", 1400),
            ):
                with self.subTest(cas=cas, largeur=largeur), tempfile.TemporaryDirectory(prefix="agida-archives-") as profil:
                    resultat = subprocess.run([
                        str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run", "--disable-background-networking",
                        f"--user-data-dir={profil}", f"--window-size={largeur},1000", "--virtual-time-budget=1200", "--dump-dom",
                        f"http://127.0.0.1:{server.server_port}/{cas}",
                    ], capture_output=True, timeout=45, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    dom = resultat.stdout.decode("utf-8", errors="replace")
                    diagnostic = dom[dom.rfind("<pre>"):] or resultat.stderr.decode("utf-8", errors="replace")[-1500:]
                    self.assertIn(">MENU_ARCHIVAGE_OK</pre>", dom, diagnostic)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
