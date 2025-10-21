from synchronisation.src.utils.conversion import parse_datetime_with_tz
from synchronisation.src.utils.fichiers import nettoyer_nom_fichier


def dossiers_declaration_manifestations_normalize(d):
    """
    Normalise la liste des dossiers_manif_sportive à partir des données brutes récupérées via l'API de déclaration-manifestations.
    :param d: Données brutes
    :return: Liste de dictionnaires, chacun représentant un dossiers_manif_sportive et ses composants associés
    """
    dossiers_manifs_sportives = []
    for doss in d :

            emplacement_geojson = f"Declaration_manifestations/{doss.get('date_debut')[:4]}/{nettoyer_nom_fichier(doss.get('nom'))}"
            
            

            dossiers_manifs_sportives.append(
                {
                    "nom_organisateur": doss.get("nom_contact"),
                    "prenom_organisateur": doss.get("prenom_contact"),
                    "qualite_declarant": doss.get("qualite_declarant_s"),
                    "structure": doss.get("structure_organisatrice_fk").get("precision_nom_s"),
                    "adresse": doss.get("structure_organisatrice_fk").get("adresse_s"),
                    "numero_telephone": doss.get("structure_organisatrice_fk").get("telephone_s"),
                    "email_structure": doss.get("structure_organisatrice_fk").get("email_s"),

                    "nom_dossier": doss.get("nom"),
                    "numero_dossier_declaration_manifestations": doss.get("pk"),
                    "etat_dossier": doss.get("etat"),
                    "date_depot": parse_datetime_with_tz(doss.get("date_creation")),
                    "date_debut_evenement": parse_datetime_with_tz(doss.get("date_debut")),
                    "date_fin_evenement": parse_datetime_with_tz(doss.get("date_fin")),
                    "emprise_voie_publique": doss.get("emprise"),
                    "evenement_competition": doss.get("competition"),
                    "description": doss.get("description"),
                    "observation": doss.get("observation"),
                    "activite": doss.get("activite"),
                    "affilie_federation_delegataire": doss.get("avec_convention_fede"),
                    "nombre_participants": doss.get("nb_participants"),
                    "nombre_max_spectateurs": doss.get("nb_spectateurs"),
                    "nombre_organisateurs": doss.get("nb_organisateurs"),
                    "nombre_vehicules_accompagnement": doss.get("nb_vehicules_accompagnement"),
                    "depart_groupe_participants": doss.get("depart_groupe"),
                    "circulation_groupee_participants": doss.get("circul_groupe"),

                    "respect_code_route": doss.get("respect_code_route"),
                    "priorite_passage": doss.get("priorite_passage"),
                    "usage_exclusif_temporaire_chaussee": doss.get("usage_temporaire"),
                    "usage_privatif_chaussee": doss.get("usage_privatif"),
                    "precisions_voies_et_horaires": doss.get("precisions_regime_circulation_detail"),

                    "vehicule_ouverture": doss.get("vehicule_ouverture"),
                    "vehicule_tete_course": doss.get("vehicule_debut"),
                    "vehicule_fin_course": doss.get("vehicule_fin"),
                    "autres_vehicules_organisation": doss.get("vehicule_organisation"),
                    "nombre_signaleurs": doss.get("nb_signaleurs"),
                    "signaleurs_postes_fixes": doss.get("nb_signaleurs_fixes"),
                    "signaleurs_mobiles_voitures": doss.get("nb_signaleurs_autos"),
                    "signaleurs_mobiles_motos": doss.get("nb_signaleurs_motos"),
                    "encadrement_police_municipale": doss.get("police_municipale"),
                    "details_encadrement_police_municipale": doss.get("detail_police_municipale"),
                    "convention_police_nationale": doss.get("police_nationale"),
                    "details_convention_police_nationale": doss.get("detail_police_nationale"),

                    "nom_coordinateur_securite": doss.get("securite_nom"),
                    "prenom_coordinateur_securite": doss.get("securite_prenom"),
                    "telephone_coordinateur_securite": doss.get("securite_tel"),
                    "email_coordinateur_securite": doss.get("securite_email"),

                    "nom_contact": doss.get("nom_contact"),
                    "prenom_contact": doss.get("prenom_contact"),
                    "telephone_contact": doss.get("tel_contact"),
                    "autres_contacts_utiles": doss.get("autres_contact"),

                    "budget_depasse_100k": doss.get("gros_budget"),
                    "manifestation_lucrative_plus_1500": doss.get("lucratif"),
                    "manifestation_titre_national_international": doss.get("delivrance_titre"),
                    "manifestation_vehicules_hors_voies_ouvertes": doss.get("vtm_hors_circulation"),
                    "charte_dispense_natura_2000": doss.get("signature_charte_dispense_site_n2k"),
                    "lieux_pdesi": doss.get("lieux_pdesi"),

                    "signataire_charte_balisage": doss.get("convention_balisage"),
                    "description_balisage": doss.get("balisage"),

                    "geometrie": doss.get("geometrie"), 
                    "emplacement": emplacement_geojson # Declaration_manifestations/{année}/{numero_dossier_declaration_manifestations}
                }
            )
    return dossiers_manifs_sportives





