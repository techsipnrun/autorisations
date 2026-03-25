from urllib.parse import unquote
from autorisations.models.models_instruction import Dossier, Demarche


def get_demarche_from_num_dossier(num_dossier):
    try:
        dossier = Dossier.objects.select_related("id_demarche").get(numero=num_dossier)
        return dossier.id_demarche
    except Dossier.DoesNotExist:
        return None


def breadcrumb_context(request):
    items = []

    match = request.resolver_match
    if not match:
        return {"breadcrumb_items": items}  # fallback sécurité

    view_name = match.view_name
    kwargs = match.kwargs

    if view_name == "preinstruction_view":
        items.append({"label": "Réception", "url": "/preinstruction/"})

    elif view_name == "preinstruction_dossier":
        items.append({"label": "Réception", "url": "/preinstruction/"})
        numero = kwargs.get("numero")
        if numero:
            items.append({"label": f"Dossier n°{numero}", "url": ""})
    
    elif view_name == "dossier_manif_sportive_sans_ds":
        items.append({"label": "Réception", "url": "/preinstruction/"})
        numero = kwargs.get("numero")
        if numero:
            items.append({"label": f"Dossier déclaration-manifestations n°{numero}", "url": ""})

    elif view_name == "preinstruction_dossier_messagerie":
        items.append({"label": "Réception", "url": "/preinstruction/"})
        numero = kwargs.get("numero")
        if numero:
            items.append({"label": f"Dossier n°{numero}", "url": f"/preinstruction/{numero}/"})
            items.append({"label": "Messagerie", "url": ""})

    elif view_name == "instruction_demarche":
        items.append({"label": "Instruction", "url": "/instruction/"})
        num_demarche = kwargs.get("num_demarche")

        try:
            demarche = Demarche.objects.get(numero=num_demarche)
            items.append({"label": demarche.type, "url": ""})
        except Demarche.DoesNotExist:
            items.append({"label": f"Démarche {num_demarche}", "url": ""})


    if view_name == "instruction_dossier":
   
        items.append({"label": "Instruction", "url": "/instruction/"})
        numero = kwargs.get("num_dossier")
        demarche = get_demarche_from_num_dossier(numero)
        if demarche:
            items.append({"label": demarche.type, "url": f"/instruction-demarche/{demarche.numero}"})

        items.append({"label": f"Dossier n°{numero}", "url": ""})



    elif view_name == "instruction_dossier_messagerie":
        items.append({"label": "Instruction", "url": "/instruction/"})
        numero = kwargs.get("num_dossier")
        demarche = get_demarche_from_num_dossier(numero)
        if demarche:
            items.append({"label": demarche.type, "url": f"/instruction-demarche/{demarche.numero}"})

        
        if numero:
            items.append({"label": f"Dossier n°{numero}", "url": f"/instruction/{numero}"})
            items.append({"label": "Messagerie", "url": ""})

    elif view_name == "instruction_dossier_consultation":
        items.append({"label": "Instruction", "url": "/instruction/"})
        numero = kwargs.get("num_dossier")
        demarche = get_demarche_from_num_dossier(numero)

        if demarche:
            items.append({"label": demarche.type, "url": f"/instruction-demarche/{demarche.numero}"})
            
        if numero:
            items.append({"label": f"Dossier n°{numero}", "url": f"/instruction/{numero}"})
            items.append({"label": "Consultation", "url": ""})

    elif view_name == "instruction_dossier_ajouter_avis":
        items.append({"label": "Instruction", "url": "/instruction/"})
        numero = kwargs.get("num_dossier")
        demarche = get_demarche_from_num_dossier(numero)

        if demarche:
            items.append({"label": demarche.type, "url": f"/instruction-demarche/{demarche.numero}"})
            
        if numero:
            items.append({"label": f"Dossier n°{numero}", "url": f"/instruction/{numero}"})
            items.append({"label": "Consultation", "url": f"/instruction/{numero}/consultation"})
            items.append({"label": "Nouvelle demande d'avis", "url": ""})

    elif view_name == "instruction_dossier_ajouter_avis_existant":
        items.append({"label": "Instruction", "url": "/instruction/"})
        numero = kwargs.get("num_dossier")
        demarche = get_demarche_from_num_dossier(numero)

        if demarche:
            items.append({"label": demarche.type, "url": f"/instruction-demarche/{demarche.numero}"})
            
        if numero:
            items.append({"label": f"Dossier n°{numero}", "url": f"/instruction/{numero}"})
            items.append({"label": "Consultation", "url": f"/instruction/{numero}/consultation"})
            items.append({"label": "Ajouter un avis existant", "url": ""})

    elif view_name == "instruction_dossier_avis":
        items.append({"label": "Instruction", "url": "/instruction/"})
        numero = kwargs.get("num_dossier")
        numero_avis = kwargs.get("avis_id")
        demarche = get_demarche_from_num_dossier(numero)

        if demarche:
            items.append({"label": demarche.type, "url": f"/instruction-demarche/{demarche.numero}"})
            
        if numero:
            items.append({"label": f"Dossier n°{numero}", "url": f"/instruction/{numero}"})
            items.append({"label": "Consultation", "url": f"/instruction/{numero}/consultation"})
            items.append({"label": f"Avis n°{numero_avis}", "url": ""})

    elif view_name == "avis_expert":
        items.append({"label": "Mes avis", "url": "/reception_avis/"})
        numero_avis = kwargs.get("avis_id")

       
        if numero_avis:
            items.append({"label": f"Avis n°{numero_avis}", "url": ""})

    elif view_name == "avis_nouvelle_demande_generique":
        items.append({"label": "Mes avis", "url": "/reception_avis/"})
 
        if numero_avis:
            items.append({"label": f"Nouvelle demande d'avis", "url": ""})

    elif view_name == "gestion_groupes":
        items.append({"label": f"Mes dossiers", "url": "/mesdossiers"})
        items.append({"label": f"Gestion des groupes", "url": ""})



    return {"breadcrumb_items": items}
