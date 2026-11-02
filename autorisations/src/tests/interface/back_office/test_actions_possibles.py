"""Premier jet des actions dans Chrome, API simulée et aucun accès BDD/NAS."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import tempfile
from threading import Thread
from unittest import skipUnless

from django.template.loader import render_to_string
from django.test import SimpleTestCase

from instruction.utils.actions_possibles import PROFILS

CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


def catalogue_fictif():
    scope = {"id_etape_id": 1, "id_demarche_id": None, "id_groupe_instructeur_id": None,
             "present_sur_dn": True, "coeur_de_parc": None, "type_manif_sportive": None}
    return {"success": True, "priorites_installees": True,
            "ordres": {code: [cle for cle, _, _ in profil["niveaux"]] for code, profil in PROFILS.items()},
            "profils": {code: {"nom": profil["nom"], "niveaux": [{"code": cle, "nom": nom, "champs": list(champs)} for cle, nom, champs in profil["niveaux"]]} for code, profil in PROFILS.items()},
            "etapes": [{"id": 1, "nom": "En pré-instruction", "est_archivage": False, "disponible_dm": False},
                       {"id": 2, "nom": "En instruction", "est_archivage": False, "disponible_dm": False},
                       {"id": 3, "nom": "À affecter", "est_archivage": False, "disponible_dm": False},
                       {"id": 4, "nom": "En réception", "est_archivage": False, "disponible_dm": True},
                       *[{"id": pk, "nom": nom, "est_archivage": True, "disponible_dm": True}
                         for pk, nom in enumerate(("Accepté", "Refusé", "Non soumis à autorisation", "Annulé", "Non répondu", "Clôture personnalisée"), 5)]],
            "demarches": [{"id": 1, "nom": "Travaux et projets avec une très longue dénomination de démonstration", "sportif": False}, {"id": 2, "nom": "Manifestations sportives", "sportif": True}],
            "groupes": [{"id": 7, "nom": "Groupe instructeur pour les travaux"}],
            "actions": [{"id": 1, "nom": "Demander des compléments", "code": "demander_des_complements",
                         "disponibles": {"dn": [1, 2], "sportif": [1, 2], "dm": []}},
                        {"id": 2, "nom": "Archiver le dossier comme non soumis à autorisation", "code": "dossier_non_soumis_a_autorisation",
                         "disponibles": {"dn": [1, 2], "sportif": [1, 2], "dm": []}},
                        {"id": 3, "nom": "Action non implémentée", "code": "inconnue",
                         "disponibles": {"dn": [], "sportif": [], "dm": []}}],
            "configurations": [{"scope": scope, "ids": [1], "actions": [1], "signature": "initiale", "niveaux": {"dn": "general", "sportif": "general"}},
                               {"scope": {**scope, "id_etape_id": 7, "present_sur_dn": False}, "ids": [94], "actions": [2], "signature": "generale-dn", "niveaux": {"dn": "general", "sportif": "general"}},
                               {"scope": {**scope, "id_etape_id": 4, "id_demarche_id": 2, "present_sur_dn": False, "coeur_de_parc": True, "type_manif_sportive": "Dossier DM"}, "ids": [85], "actions": [2], "signature": "specifique-dm", "niveaux": {"dm": "demarche_coeur"}}]}


@skipUnless(CHROME.exists(), "Chrome headless indisponible.")
class ActionsPossiblesInterfaceTests(SimpleTestCase):
    def test_configuration_priorites_simulation_et_responsive(self):
        src = Path(__file__).resolve().parents[3]
        contenu = render_to_string("backoffice/back_office_actions.html")
        script = r"""
        window.addEventListener('load', async () => {
            const q=selector=>document.querySelector(selector);
            const assert=(condition,message)=>{if(!condition)throw Error(message);};
            const attendre=async predicate=>{for(let i=0;i<160;i++){if(predicate())return;await new Promise(resolve=>setTimeout(resolve,20));}throw Error('Attente trop longue');};
            const changer=(element,value)=>{element.value=value;element.dispatchEvent(new Event('change',{bubbles:true}));};
            const verifierLargeur=()=>{
                const limite=q('[data-panel]').getBoundingClientRect().right;
                document.querySelectorAll('input,select,button').forEach(element=>{
                    const modal=element.closest('dialog');
                    const bord=modal?modal.getBoundingClientRect().right:limite;
                    if(element.getClientRects().length)assert(element.getBoundingClientRect().right<=bord+1,'Contrôle hors du panneau : '+(element.name||element.textContent));
                });
                assert(document.documentElement.scrollWidth<=innerWidth+1,'Débordement horizontal');
            };
            window.confirm=()=>true;
            const sortie=document.createElement('pre');document.body.append(sortie);
            try {
                await attendre(()=>q('[data-actions-etape]').options.length===11);
                assert(!q('[data-actions-tab="compatibilites"]'),'Section de compatibilités supprimée');
                assert(!q('[data-actions-common]').hidden,'Critères communs visibles dans Configurations');
                assert(!q('[data-actions-recharger]'),'Pas de bouton Recharger');
                assert(q('[data-actions-ajouter]').disabled,'Ajout interdit sans étape');
                changer(q('[data-actions-etape]'),'1');
                assert(q('[data-actions-modifier]'),'Configuration générale visible');
                assert(!q('[data-actions-configurations]').textContent.includes('BDD'),'Pas d’identifiants techniques');
                q('[data-actions-ajouter]').click();
                let ajout=q('[data-actions-edit-form]');
                assert(q('dialog').open&&q('dialog').matches(':modal'),'Édition en premier plan');
                assert(q('dialog').getBoundingClientRect().left>=q('.back-office-content').getBoundingClientRect().left,'Navigation non recouverte');
                assert(ajout.elements.id_etape_id.value==='1'&&ajout.elements.id_etape_id.disabled,'Étape héritée et verrouillée');
                ['present_sur_dn','id_demarche_id','id_groupe_instructeur_id'].forEach(key=>{
                    assert(ajout.elements[key].required,'Champ obligatoire : '+key);
                    assert(!ajout.elements[key].closest('label').querySelector('.bo-actions-field-required').hidden,'Étoile visible : '+key);
                });
                verifierLargeur();
                q('[data-actions-fermer]').click();
                assert(!q('dialog').open,'Fermeture par croix');
                q('[data-actions-modifier]').click();
                const form=q('[data-actions-edit-form]');
                assert(form.elements.niveau.value==='general','Niveau existant sélectionné');
                assert(form.elements.id_demarche_id.closest('label').hidden,'Critères absents masqués');
                const box=form.querySelector('[name=action][value="2"]');box.click();
                assert(form.querySelector('[name=action][value="3"]').disabled,'Action non prise en charge grisée');
                assert(form.querySelector('[name=action][value="3"]').closest('label').textContent.includes('implémenté'),'Raison de l’indisponibilité visible');
                verifierLargeur();
                form.querySelector('[type=submit]').click();
                await attendre(()=>q('[data-actions-editor-status]')?.classList.contains('is-error'));
                assert(box.checked&&!q('[data-actions-editor]').hidden,'Erreur conserve la saisie');
                assert(form.elements.id_etape_id.disabled,'Étape toujours verrouillée après erreur');
                form.querySelector('[type=submit]').click();
                await attendre(()=>q('[data-actions-editor]').hidden&&q('[data-actions-status]').textContent.startsWith('Configuration enregistr'));
                assert(q('[data-actions-configurations]').textContent.includes('non soumis'),'Toutes les actions sauvegardées affichées');
                q('[data-actions-tab="priorites"]').click();
                assert(q('[data-actions-common]').textContent.includes('Étape · Présence sur DN'),'Critères communs visibles');
                assert(!q('[data-actions-priorites]').textContent.includes('Critères communs'),'Critères communs non répétés dans les blocs');
                if(innerWidth>1000)assert(q('.bo-actions-priority').getBoundingClientRect().width<q('[data-actions-priorites]').getBoundingClientRect().width,'Priorité compacte');
                q('[data-actions-move="2"][data-direction="-1"]').click();
                q('[data-actions-move="1"][data-direction="-1"]').click();
                assert(q('[data-actions-priorites]').firstElementChild.textContent.includes('Configuration générale'),'Priorité déplacée localement');
                q('[data-actions-enregistrer-priorites]').click();
                await attendre(()=>q('[data-actions-status]').textContent==='Priorités enregistrées.');
                q('[data-actions-tab="tester"]').click();
                assert(q('[data-actions-common]').hidden,'Critères communs masqués dans le test');
                const test=q('[data-actions-test-form]');
                [...q('[data-actions-test-fictif]').querySelectorAll('select')].filter(input=>!input.closest('label').hidden).forEach(input=>assert(input.required,'Contexte obligatoire : '+input.name));
                changer(test.elements.id_etape_id,'1');
                changer(test.elements.id_demarche_id,'1');changer(test.elements.id_groupe_instructeur_id,'__aucun__');
                test.querySelector('[type=submit]').click();
                await attendre(()=>q('[data-actions-resultat] .is-winner'));
                assert(q('[data-actions-resultat]').textContent.includes('Priorité 1'),'Niveau gagnant visible');
                assert(q('[data-actions-resultat]').textContent.includes('Écarté'),'Niveaux écartés visibles');
                assert(q('[data-actions-tested-context]').textContent.includes('Aucun groupe affecté'),'Contexte testé explicite');
                assert(q('[data-actions-retained-configuration]').textContent.includes('Tous les groupes'),'Configuration gagnante distinguée du contexte');
                assert(q('[data-actions-tested-context] dt').textContent==='Étape','Critères du contexte étiquetés');
                assert(!q('[data-actions-resultat]').textContent.includes('Règles BDD'),'Pas d’identifiants dans le résultat');
                verifierLargeur();
                changer(test.elements.mode,'dossier');
                assert(test.elements.etape_fictive.required,'Étape fictive obligatoire');
                test.elements.numero.value='12';test.elements.numero.dispatchEvent(new Event('input'));
                await attendre(()=>q('#bo-actions-dossiers option[value="123"]'));
                test.elements.numero.value='123';test.elements.numero.dispatchEvent(new Event('input'));
                assert(test.elements.etape_fictive.value==='1','Étape du dossier automatiquement renseignée');
                changer(test.elements.etape_fictive,'2');
                test.elements.numero.dispatchEvent(new Event('change'));
                assert(test.elements.etape_fictive.value==='2','Étape fictive modifiable et conservée');
                test.querySelector('[type=submit]').click();
                await attendre(()=>q('[data-actions-resultat]').textContent.includes('En instruction'));
                test.elements.numero.value='999';test.elements.numero.dispatchEvent(new Event('input'));
                changer(test.elements.etape_fictive,'2');test.querySelector('[type=submit]').click();
                await attendre(()=>q('[data-actions-resultat]').classList.contains('is-error'));
                const erreur=q('[data-actions-resultat]');
                assert(parseFloat(getComputedStyle(erreur).paddingLeft)>0,'Erreur avec padding');
                verifierLargeur();
                changer(q('[data-actions-circuit]'),'dm');
                assert(q('[data-actions-priorites]').children.length===2,'Deux niveaux dans les priorités DM');
                assert(q('[data-actions-priorites] strong').textContent==='Cœur de parc','Nom simplifié du premier niveau DM');
                const etapes=q('[data-actions-etape]');
                ['1','2','3'].forEach(id=>assert(etapes.querySelector('option[value="'+id+'"]').disabled,'Étape DN grisée : '+id));
                ['4','5','6','7','8','9','10'].forEach(id=>assert(!etapes.querySelector('option[value="'+id+'"]').disabled,'Réception et archivages disponibles : '+id));
                assert(etapes.value===''&&q('[data-actions-ajouter]').disabled,'Étape incompatible effacée au changement de circuit');
                assert(!q('[data-actions-resultat]').classList.contains('is-error'),'Changement de circuit efface le rouge');
                assert(getComputedStyle(q('.bo-actions-empty')).backgroundColor==='rgba(0, 0, 0, 0)','État vide sans fond rouge');
                assert(test.elements.type_manif_sportive.value==='Dossier DM','DM seul sélectionné');
                assert(test.elements.present_sur_dn.value==='false','DM absent de DN');
                assert(test.elements.id_groupe_instructeur_id.closest('label').hidden,'Pas de critère groupe pour DM');
                q('[data-actions-tab="configurations"]').click();
                assert(!q('[data-actions-configurations]').textContent.includes('Démarche manifestations sportives'),'Ancien niveau DM retiré des configurations');
                changer(etapes,'5');
                assert(!q('[data-actions-ajouter]').disabled,'Archivage sélectionnable sans règle DM');
                changer(etapes,'7');
                assert(!q('[data-actions-modifier]'),'Configuration générale DN absente du circuit DM');
                assert(!q('[data-actions-configurations] .bo-actions-chip'),'Aucune action générale DN affichée pour DM');
                changer(etapes,'4');
                assert(!q('[data-actions-configurations] h3').textContent.includes('Dossier DM'),'Type DM non répété dans le titre de la carte');
                assert(!q('[data-actions-configurations] h2').textContent.includes('type DM'),'Type DM non répété dans le titre du niveau');
                q('[data-actions-modifier]').click();
                assert(q('[data-actions-edit-form]').elements.type_manif_sportive.disabled,'Type verrouillé en modification');
                assert(q('[data-actions-edit-form]').elements.id_demarche_id.disabled&&q('[data-actions-edit-form]').elements.id_demarche_id.value==='2','Démarche sportive préremplie et verrouillée en modification');
                q('[data-actions-fermer]').click();
                q('[data-actions-ajouter]').click();
                assert(!q('[data-actions-common]').hidden&&q('[data-actions-common]').textContent==='Critères communs obligatoires : Étape · Présence sur DN (Non) · Démarche (manifestations sportives)','Critères communs DM explicités');
                const dm=q('[data-actions-edit-form]');
                assert([...dm.elements.niveau.options].map(option=>option.value).join(',')==='demarche_coeur,general','Deux niveaux DM dans le formulaire');
                assert(dm.elements.id_etape_id.value==='4','Configuration DM sur l’étape autorisée sélectionnée');
                assert(dm.elements.id_demarche_id.value==='2'&&dm.elements.id_demarche_id.required&&dm.elements.id_demarche_id.disabled,'Démarche sportive obligatoire, préremplie et grisée en création');
                assert(dm.elements.type_manif_sportive.value==='Dossier DM'&&dm.elements.type_manif_sportive.disabled,'Type DM imposé et grisé dans nouvelle configuration');
                changer(dm.elements.niveau,'general');
                assert(dm.elements.type_manif_sportive.value==='Dossier DM'&&dm.elements.type_manif_sportive.required&&dm.elements.type_manif_sportive.disabled,'Générale DM explicitement typée, obligatoire et verrouillée');
                assert(dm.elements.present_sur_dn.value==='false','Générale DM absente de DN');
                ['id_demarche_id','id_groupe_instructeur_id','coeur_de_parc'].forEach(key=>{
                    assert(dm.elements[key].value===''&&dm.elements[key].closest('label').hidden,'Critère général DM laissé vide : '+key);
                });
                changer(dm.elements.niveau,'demarche_coeur');
                assert(dm.elements.id_demarche_id.value==='2'&&dm.elements.id_demarche_id.disabled,'Démarche rétablie et verrouillée après changement de niveau');
                changer(dm.elements.niveau,'general');
                assert(q('[data-actions-scope-help]').textContent.includes('réservée aux dossiers DM seuls'),'Portée générale DM expliquée');
                dm.querySelector('[type=submit]').click();
                await attendre(()=>q('[data-actions-editor-status]').classList.contains('is-error'));
                assert(dm.elements.type_manif_sportive.disabled&&dm.elements.id_etape_id.disabled,'Étape et type toujours verrouillés après erreur');
                verifierLargeur();
                q('dialog').dispatchEvent(new Event('cancel',{cancelable:true}));
                assert(!q('dialog').open,'Fermeture avec Échap');
                changer(q('[data-actions-circuit]'),'dn');
                assert([...etapes.options].every(option=>!option.disabled),'Étapes DN toutes rétablies');
                sortie.textContent='ACTIONS_POSSIBLES_OK';
            } catch(error) {sortie.textContent='ECHEC : '+error.message;}
        });
        """
        page = f'''<!doctype html><html><head><meta charset="utf-8">
        <link rel="stylesheet" href="/static/backoffice/css/back_office.css">
        <link rel="stylesheet" href="/static/backoffice/css/back_office_actions.css">
        <script src="/static/backoffice/js/back_office_actions.js" defer></script></head>
        <body><div class="back-office-layout"><aside class="back-office-sidebar"></aside><main class="back-office-content"><section class="back-office-panel" data-panel="actions">{contenu}</section></main></div><script>{script}</script></body></html>'''.encode()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def repondre(self, data, mime="application/json", status=200):
                self.send_response(status)
                self.send_header("Content-Type", mime)
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/":
                    self.server.donnees = catalogue_fictif()
                    self.server.posts = []
                    self.server.erreur = True
                    self.repondre(page, "text/html; charset=utf-8")
                elif self.path.startswith("/static/backoffice/"):
                    fichier = src / "backoffice/static" / self.path.removeprefix("/static/")
                    self.repondre(fichier.read_bytes(), "text/css" if fichier.suffix == ".css" else "application/javascript")
                elif self.path == "/back-office/actions/":
                    self.repondre(json.dumps(self.server.donnees).encode())
                elif self.path.startswith("/back-office/actions/dossiers/?"):
                    self.repondre(json.dumps({"success": True, "dossiers": [{"numero": "123", "etape": 1, "etape_nom": "En pré-instruction", "nom": "Projet"}]}).encode())
                else:
                    self.send_error(404)

            def do_POST(self):
                donnees = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                self.server.posts.append((self.path, donnees))
                if self.path.endswith("/configuration/"):
                    if donnees["circuit"] == "dm" and not donnees["actions"]:
                        self.repondre(json.dumps({"success": False, "error": "Choisissez au moins une action."}).encode(), status=400)
                        return
                    if self.server.erreur:
                        self.server.erreur = False
                        self.repondre(json.dumps({"success": False, "error": "Erreur simulée"}).encode(), status=400)
                        return
                    self.server.donnees["configurations"][0]["actions"] = donnees["actions"]
                elif self.path.endswith("/priorites/"):
                    self.server.donnees["ordres"][donnees["circuit"]] = donnees["ordre"]
                elif self.path.endswith("/tester/"):
                    if donnees.get("numero") == "999":
                        self.repondre(json.dumps({"success": False, "error": "Dossier DN introuvable."}).encode(), status=400)
                        return
                    scope = dict(donnees.get("contexte") or {**self.server.donnees["configurations"][0]["scope"], "id_demarche_id": 1})
                    scope["id_etape_id"] = donnees.get("etape_fictive") or 1
                    retenue = {**self.server.donnees["configurations"][0]["scope"], "id_etape_id": scope["id_etape_id"]}
                    result = {"success": True, "circuit": "dn", "contexte": scope,
                              "configuration_retenue": retenue,
                              "niveau_retenu": {"nom": "Configuration générale", "priorite": 1},
                              "actions": ["Demander des compléments"],
                              "niveaux": [{"code": "general", "nom": "Configuration générale", "priorite": 1, "statut": "retenue", "regles": [1], "actions": ["Demander des compléments"]},
                                          {"code": "demarche", "nom": "Démarche", "priorite": 2, "statut": "ecartee", "regles": [2], "actions": ["Autre action"]}]}
                    self.repondre(json.dumps(result).encode())
                    return
                self.repondre(b'{"success":true}')

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for largeur in (390, 1600):
                with self.subTest(largeur=largeur), tempfile.TemporaryDirectory(prefix="agida-actions-") as profil:
                    resultat = subprocess.run([str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run", "--disable-background-networking",
                        f"--user-data-dir={profil}", f"--window-size={largeur},1000", "--virtual-time-budget=12000", "--dump-dom", f"http://127.0.0.1:{server.server_port}/"],
                        capture_output=True, timeout=45, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    dom = resultat.stdout.decode("utf-8", errors="replace")
                    self.assertTrue(">ACTIONS_POSSIBLES_OK</pre>" in dom, dom[-1600:] + resultat.stderr.decode("utf-8", errors="replace")[-600:])
                    posts = server.posts
                    self.assertEqual(len(posts), 7)
                    self.assertEqual(posts[1][1]["actions"], [1, 2])
                    self.assertEqual(next(payload for _, payload in posts if payload.get("numero") == "123")["etape_fictive"], 2)
                    self.assertEqual(posts[-1][1]["scope"]["type_manif_sportive"], "Dossier DM")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
