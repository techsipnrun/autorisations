import os
import smbclient


def ecrire_uploadedfile_sur_nas(fichier_django, chemin_destination):
    try:
        username = os.getenv("NAS_USER", "admin_auto")
        password = os.getenv("NAS_PASSWORD", ";A3n_@U:t0!P3n#")

        smbclient.ClientConfig(username=username, password=password)

        dossier_parent = os.path.dirname(chemin_destination)
        if not smbclient.path.exists(dossier_parent):
            smbclient.makedirs(dossier_parent)
            print(f"[NAS] 📁 Dossier créé : {dossier_parent}")

        with smbclient.open_file(chemin_destination, mode="wb") as dst:
            for chunk in fichier_django.chunks():
                dst.write(chunk)

        print(f"[NAS] ✅ Fichier {fichier_django.name} écrit sur {chemin_destination}")
        return True

    except PermissionError as e:
        print(f"[NAS] ⛔ Accès refusé : {e}")
    except FileNotFoundError:
        print(f"[NAS] ❌ Fichier source introuvable (UploadFile vide ?)")
    except Exception as e:
        print(f"[NAS] ⚠️ Erreur inattendue : {e}")

    return False


# ------------------------------------------------------------
# SIMULATION d’un objet Django UploadedFile
# ------------------------------------------------------------
class FichierSimule:
    def __init__(self, chemin_local):
        self.chemin_local = chemin_local
        self.name = os.path.basename(chemin_local)

    def chunks(self, chunk_size=8192):
        with open(self.chemin_local, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk


# ------------------------------------------------------------
# TEST
# ------------------------------------------------------------
if __name__ == "__main__":
    # Fichier à envoyer
    chemin_local = r"C:\Users\lcalu\Desktop\Projet Autorisations\Carte_Coeur_De_Parc_Activités_Commerciales.pdf"

    # Fichier de destination sur le NAS
    chemin_nas = r"\\x-wing\autodev_data\Annexes\dfefefef\test_depuis_fonction.pdf"

    fichier = FichierSimule(chemin_local)
    success = ecrire_uploadedfile_sur_nas(fichier, chemin_nas)

    if success:
        print("✅ Test terminé avec succès — fichier présent sur le NAS.")
    else:
        print("❌ Échec du test — voir messages ci-dessus.")
