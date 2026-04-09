import mimetypes
import os
import re

from dotenv import load_dotenv
import smbclient

from get_methods import ajouter_pj_avis, get_access_token, get_file, get_pj_avis, get_pj_dossier, rendre_avis


def _normalize_unc_path(p: str) -> str:
    if not p:
        return p

    # 1) Unifier les séparateurs
    p = p.strip().replace("/", "\\")

    # 2) Forcer EXACTEMENT deux backslashes au début (UNC),
    #    même si on en reçoit 1, 3, 4...
    p = re.sub(r"^\\+", r"\\\\", p)

    # 3) Réduire les backslashes multiples ailleurs à un seul,
    #    en conservant le préfixe UNC "\\"
    p = "\\\\" + re.sub(r"\\{2,}", r"\\", p[2:])

    return p


def main():
    token = get_access_token()

    # NUMEROS POUR LE TEST
    # avis_id = 272064
    # dossier_id = 104487

    # GET PJ AVIS
    """
    print("\n--- TEST get_pj_avis ---")
    pj_avis = get_pj_avis(token, avis_id)
    print(f"Nb PJ avis : {len(pj_avis)}")
    for i, pj in enumerate(pj_avis, start=1):
        print(f"{i}. fichier={pj.get('fichier')} | remonte_doc_officiel={pj.get('demande_de_remonte_en_doc_officiel_b')}")
    """

    # GET PJ DOSSIER
    """
    print("\n--- TEST get_pj_dossier ---")
    pj_dossier = get_pj_dossier(token, dossier_id)
    print(f"Nb PJ dossier : {len(pj_dossier)}")
    for i, pj in enumerate(pj_dossier[:5], start=1):  # limite à 5 pour affichage
        print(
            f"{i}. id={pj.get('id')} | nom={pj.get('nom')} | "
            f"document_attache={pj.get('document_attache')} | "
            f"date_televersement={pj.get('date_televersement')}"
        )
    

    # GET FILE
    for pj in pj_dossier:
        if pj.get("document_attache"):
            media_path = pj["document_attache"]
            content = get_file(token, media_path)
            print("Fichier téléchargé :", len(content), "octets")
            print(f"type : {type(content)}")

            # with open("test_document.pdf", "wb") as f:
            #     f.write(content)


            break
    """

    # POST rendre avis
    """
    avis_id = 877770
    print("\n--- TEST rendre_avis ---")
    rep = rendre_avis(
        token=token,
        avis_id=avis_id,
        reponse_avis=1,
        prescriptions="Voici mes prescriptions de test."
    )

    print("Réponse API :", rep)
    """

    # POST ajouter pj avis
    """
    avis_id = 877770
    print("\n--- TEST ajouter_pj_avis ---")
    load_dotenv(".env.dev")
    fichier_test = "test_document.pdf"

    file_path = _normalize_unc_path(os.path.join(os.environ.get("NAS_ROOT"), fichier_test))
        
    
    rep = ajouter_pj_avis(
        token=token,
        avis_id=avis_id,
        file_path=file_path,
        demande_de_remonte_en_doc_officiel_b=False,
    )

    print("Réponse API :", rep)
    """

if __name__ == "__main__":
    main()