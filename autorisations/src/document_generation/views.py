"""Page dev : validation et téléchargement d'un DOCX de test en mémoire."""

from copy import deepcopy
from hashlib import sha256
import json
import logging
from uuid import uuid4

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import OperationalError, ProgrammingError
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect, QueryDict
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.urls import reverse

from autorisations.models.models_generation import Balise, DocumentTemplate, DocumentGeneration
from autorisations.models.models_instruction import Dossier, Demarche
from instruction.templatetags.group_tags import est_concerne_par_le_dossier
from .forms import DynamicDocumentForm
from .services.context_utils import merge_contexts
from .services.preparation import DocumentPreparationService
from .services.validation import GenerationContextValidator, lire_contexte, valeur_vide
from .services.docx_renderer import DocxRenderer, DocxRenderError, build_preview_filename
from .services.pdf_preview import PdfPreviewService, PdfPreviewError
from .services.output import DocumentOutputError
from .services.record_generation import RecordGenerationService
from .services.history import dossier_history, read_generated_document
from .services.numbers import number_kind, session_state, selected_number
from .services.filename import resolve_filename
from .services.filename_editor import filename_editor_context

logger = logging.getLogger(__name__)


def _scroll_position(request):
    if request.method != "POST":
        return None
    result = {}
    for axis in ("x", "y"):
        try:
            result[axis] = max(0, min(10000000, int(request.POST.get(f"_scroll_{axis}", "0"))))
        except (TypeError, ValueError):
            result[axis] = 0
    return result


def _dossier_context(request, num_dossier):
    if settings.ENVIRONMENT != "dev":
        raise Http404
    dossier = get_object_or_404(Dossier.objects.select_related("id_demarche", "id_etape_dossier", "id_groupeinstructeur"), numero=num_dossier)
    request.dossier_courant = dossier
    if not request.user.is_superuser and not est_concerne_par_le_dossier(request.user, dossier):
        raise PermissionDenied("Vous n'êtes pas autorisé à travailler sur ce dossier.")
    return dossier


def _work_context(request, num_dossier, template_id):
    dossier = _dossier_context(request, num_dossier)
    template = get_object_or_404(DocumentTemplate, pk=template_id, actif=True)
    selected = request.GET.get("demarche", dossier.id_demarche_id)
    try:
        selected = int(selected)
    except (TypeError, ValueError):
        raise Http404 from None
    if template.demarches.exists() and not template.demarches.filter(pk=selected).exists():
        raise Http404("Ce modèle n'est pas disponible pour la démarche du dossier.")
    return dossier, template


@login_required
@require_http_methods(["GET", "POST"])
def dossier_generation(request, num_dossier):
    dossier = _dossier_context(request, num_dossier)
    try:
        selected_id = int(request.GET.get("demarche", dossier.id_demarche_id))
    except (ValueError, TypeError):
        raise Http404 from None
    selected = dossier.id_demarche if selected_id == dossier.id_demarche_id else get_object_or_404(Demarche, pk=selected_id)
    demarches = Demarche.objects.exclude(type__isnull=True).exclude(type="").order_by("type", "numero")
    candidates = DocumentTemplate.objects.filter(actif=True, rapport_validation__valide=True).filter(
        Q(demarches=selected) | Q(demarches__isnull=True)
    ).distinct().order_by("nom")
    templates = [template for template in candidates if not template.erreurs_configuration()]
    original = dossier.id_demarche
    from instruction.utils.dossier_utils import build_timeline_for_dossier
    shell = {
        "dossier": dossier, "demarche": original, "etape_actuelle": dossier.id_etape_dossier,
        "dossier_actions": build_timeline_for_dossier(dossier),
        "demarches_generation": demarches, "selected_demarche": selected, "templates_generation": templates,
        "breadcrumb_items": [
            {"label": "Instruction", "url": "/instruction/"},
            {"label": original.type, "url": f"/instruction-demarche/{original.numero}"},
            {"label": f"Dossier n°{dossier.numero}", "url": f"/instruction/{dossier.numero}/"},
            {"label": "Génération de fichier", "url": ""},
        ],
    }
    template_id = request.GET.get("template")
    if template_id:
        template = next((item for item in templates if str(item.pk) == template_id), None)
        if template is None:
            raise Http404("Ce template n'est pas disponible, valide et complet pour la démarche sélectionnée.")
        return generer_document(request, num_dossier, template.pk, _shell=shell, _work=(dossier, template))
    if request.method == "POST":
        raise Http404("Sélectionnez un template.")
    response = render(request, "document_generation/dossier_generation.html", {**shell, **dossier_history(dossier)})
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_http_methods(["GET", "POST"])
def generer_document(request, num_dossier, template_id, _shell=None, _work=None):
    dossier, template = _work or _work_context(request, num_dossier, template_id)
    # Le GET restaure les saisies, sans rejouer la génération ni la conversion PDF.
    draft_key = sha256(request.get_full_path().encode()).hexdigest()
    drafts = request.session.get('document_generation_drafts', {})
    draft = drafts.get(draft_key, {}) if request.method == 'GET' else {}
    submitted = request.POST if request.method == 'POST' else None
    if draft:
        submitted = QueryDict('', mutable=True)
        for name, values in draft['values'].items():
            submitted.setlist(name, values)
        # Une configuration modifiée dans le back-office remplace l'ancien nom
        # du brouillon, tout en conservant les autres saisies de l'instructeur.
        if draft.get('template_filename') != template.nom_fichier:
            submitted.pop('output_filename', None)
        # Seul le retour immédiat d'un POST en cours peut conserver la sélection.
        # Ni une nouvelle ouverture ni une actualisation ne reprennent ce numéro.
        if not draft.pop('return_number_once', False):
            submitted.pop('number_selection', None)
        draft['values'].pop('number_selection', None)
        request.session['document_generation_drafts'] = drafts
    action = request.POST.get('action') if request.method == 'POST' else None

    form, context_json, final_context = None, None, None
    known_form = None
    known_edited = submitted is not None and submitted.get("edit_known") == "1"
    rows, errors = [], []
    complete = False
    generated_file = draft.get('generated_file')
    generation_error = draft.get('generation_error')
    numbering_kind = None
    number_state = {}
    number_reservation = None
    filename_error = None
    filename_pattern = submitted.get('output_filename', template.nom_fichier) if submitted is not None else template.nom_fichier
    if not isinstance(filename_pattern, str):
        filename_pattern = ''
    filename_values = {}
    try:
        if isinstance(template.id_nature_id, int):
            numbering_kind = number_kind(template)
        if numbering_kind:
            number_state = session_state(request, dossier, template)
            token = submitted.get('number_selection', '') if submitted is not None else ''
            number_reservation = selected_number(token, dossier, template, request.user)
        dossier._generation_number = number_reservation.numero if number_reservation else None
        filename_values = filename_editor_context(filename_pattern, dossier, dossier._generation_number)
        prepared = DocumentPreparationService().prepare(dossier, template)
        rows, errors = [row for row in prepared['known_rows'] if row['code'] != 'document.numero'], list(prepared["errors"])
        if not errors:
            editable = [b for b in prepared["balises"] if b.mode == Balise.Mode.CONNUE
                        and b.code != 'document.numero' and b.code in {row["code"] for row in rows}]
            initial = {f"balise_{b.pk}": lire_contexte(prepared["known_context"], b.code) for b in editable}
            for b in editable:
                if b.type == Balise.Type.BOOLEAN and initial[f"balise_{b.pk}"] is not None:
                    initial[f"balise_{b.pk}"] = "true" if initial[f"balise_{b.pk}"] else "false"
            known_form = DynamicDocumentForm(
                data=submitted if known_edited else None, prefix="known", balises=editable, initial=initial)
            known_valid = True
            if known_edited:
                known_valid = known_form.is_valid()
                for name, b in known_form.balise_map.items():
                    if name in known_form.cleaned_data and b.required and valeur_vide(known_form.cleaned_data[name]):
                        known_form.add_error(name, "La valeur saisie ne peut pas être vide.")
                        known_valid = False
            effective_context = deepcopy(prepared["known_context"])
            form = DynamicDocumentForm(data=submitted,
                                       balises=prepared["form_balises"])
            if submitted is not None and form.is_valid() and known_valid:
                if known_edited:
                    # Seules les balises connues affichées et typées sont modifiables.
                    # La copie reste locale à cette requête, sans écriture sur le dossier.
                    for name, b in known_form.balise_map.items():
                        node = effective_context
                        parts = b.code.split(".")
                        for part in parts[:-1]:
                            node = node[part]
                        node[parts[-1]] = known_form.cleaned_data[name]
                manual = form.to_manual_values()
                validator = GenerationContextValidator()
                validation = validator.validate(prepared["balises"], effective_context, manual)
                if not validation["missing"] and not validation["errors"]:
                    merged = merge_contexts(effective_context, form.to_context())
                    # Les compléments CONNUS sont désormais dans le contexte.
                    # Seules les balises manuelles gardent leur canal de saisie.
                    manual_codes = {b.code for b in prepared["balises"] if b.mode == Balise.Mode.A_RENSEIGNER}
                    validation = validator.validate(prepared["balises"], merged,
                                                    {code: value for code, value in manual.items() if code in manual_codes})
                    complete = not validation["missing"] and not validation["errors"]
                    if complete:
                        final_context = validation["resolved"]
                        if number_reservation:
                            node = final_context.setdefault('document', {})
                            if not isinstance(node, dict) or node.get('numero', number_reservation.numero) != number_reservation.numero:
                                raise ValidationError('Le contexte contient un numéro différent de la réservation.')
                            node['numero'] = number_reservation.numero
                        if numbering_kind and not number_reservation:
                            filename_error = 'Générez ou récupérez le numéro du document.'
                            complete = False
                        if filename_pattern:
                            try:
                                resolve_filename(filename_pattern, dossier, document_number=dossier._generation_number)
                            except (ValueError, ValidationError) as exc:
                                filename_error = str(exc)
                                complete = False
                        context_json = json.dumps(final_context, cls=DjangoJSONEncoder, ensure_ascii=False, indent=2)
                        if action == "generate_file" and complete:
                            with DocxRenderer().render_to_memory(prepared["template_bytes"], final_context) as buffer:
                                options = {}
                                if number_reservation is not None:
                                    options['number_reservation'] = number_reservation
                                if filename_pattern:
                                    options['filename_pattern'] = filename_pattern
                                generated_file = RecordGenerationService().save(
                                    buffer, template, dossier, request.user, final_context, prepared['template_bytes'], **options)
                        if action == "generate_docx" and complete:
                            buffer = DocxRenderer().render_to_memory(prepared["template_bytes"], final_context)
                            response = FileResponse(
                                buffer, as_attachment=True,
                                filename=build_preview_filename(template, dossier),
                                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            )
                            response["Cache-Control"] = "private, no-store"
                            response["X-Content-Type-Options"] = "nosniff"
                            return response
                        if action == "preview_pdf" and complete:
                            with DocxRenderer().render_to_memory(prepared["template_bytes"], final_context) as buffer:
                                PdfPreviewService().create_preview(buffer, request.user.pk, dossier.pk, template.pk)
                if not complete and action is not None:
                    for entry in validation["errors"]:
                        form.add_error(None, entry["message"])
                    if validation["missing"] and any(entry['code'] != 'document.numero' for entry in validation['missing']):
                        form.add_error(None, "Certaines informations obligatoires restent à renseigner.")
                    elif validation['missing']:
                        filename_error = 'Générez ou récupérez le numéro du document avant de poursuivre.'
    except DocumentOutputError as exc:
        logger.exception("Échec génération NAS dossier=%s template=%s utilisateur=%s", dossier.numero, template.pk, request.user.pk)
        generation_error = str(exc)
    except PdfPreviewError as exc:
        logger.exception("Échec aperçu PDF dossier=%s template=%s utilisateur=%s", dossier.numero, template.pk, request.user.pk)
        errors.append(str(exc))
    except DocxRenderError as exc:
        logger.exception("Échec du rendu DOCX de test dossier=%s template=%s utilisateur=%s",
                         dossier.numero, template.pk, getattr(request.user, "pk", None))
        if action == "generate_file":
            generation_error = f"Impossible de générer le document : {exc}"
        else:
            errors.append(f"Impossible de générer le document : {exc}")
    except (ValueError, ValidationError) as exc:
        errors.append(str(exc))
        form = None
    except (OperationalError, ProgrammingError):
        logging.getLogger(__name__).exception("Échec de préparation du contexte de document")
        errors.append("Les données nécessaires sont inaccessibles. Vérifiez les scripts SQL et les droits en dev.")
        form = None

    if request.method == 'POST':
        values = {name: values for name, values in request.POST.lists()
                  if name.startswith(('balise_', 'known-balise_')) or name in ('edit_known','number_selection','output_filename')}
        keep_number = not (action == 'generate_file' and generated_file and not generation_error)
        if not keep_number:
            values.pop('number_selection', None)
        drafts.pop(draft_key, None)
        drafts[draft_key] = {'values': values, 'generated_file': generated_file,
                             'template_filename': template.nom_fichier,
                             'return_number_once': keep_number,
                             'generation_error': generation_error, 'errors': errors,
                             'scroll_position': _scroll_position(request)}
        # Limite le nombre de brouillons conservés dans la session.
        request.session['document_generation_drafts'] = dict(list(drafts.items())[-5:])
        response = HttpResponseRedirect(request.get_full_path())
        response.status_code = 303
        response['Cache-Control'] = 'private, no-store'
        return response
    errors = list(dict.fromkeys([*errors, *draft.get('errors', [])]))
    scroll_position = draft.pop('scroll_position', None)
    if scroll_position is not None:
        request.session['document_generation_drafts'] = drafts

    preview_exists = False
    try:
        preview_exists = PdfPreviewService().available(request.user.pk, dossier.pk, template.pk)
    except (PdfPreviewError, OSError):
        logger.exception("Stockage aperçu inaccessible dossier=%s template=%s utilisateur=%s", dossier.numero, template.pk, request.user.pk)
    preview_url = reverse("document_generation:preview_pdf", args=[dossier.numero, template.pk]) + f"?v={uuid4().hex}" if preview_exists else None
    if preview_url and _shell:
        preview_url += f"&demarche={_shell['selected_demarche'].pk}"
    response = render(request, "document_generation/dossier_generation.html" if _shell else "document_generation/generation_form.html", {
        **(_shell or {}),
        **dossier_history(dossier),
        "dossier": dossier, "document_template": template, "resolved_balises": rows,
        "form": form, "known_form": known_form, "known_edited": known_edited, "errors": errors, "complete": complete,
        "final_context": final_context, "context_json": context_json,
        "preview_exists": preview_exists, "preview_url": preview_url,
        "generated_file": generated_file,
        "generation_error": generation_error,
        "scroll_position": scroll_position,
        'numbering_kind': numbering_kind, 'number_state': number_state, 'number_reservation': number_reservation,
        'filename_pattern': filename_pattern, 'filename_values': filename_values, 'filename_error': filename_error,
    })
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_http_methods(['GET'])
def download_generated(request, num_dossier, generation_id):
    dossier = _dossier_context(request, num_dossier)
    generation = get_object_or_404(DocumentGeneration.objects.select_related('id_document'),
                                   pk=generation_id, id_dossier=dossier)
    try:
        buffer = read_generated_document(generation.id_document)
    except DocumentOutputError as exc:
        logger.exception('Lecture génération impossible dossier=%s generation=%s user=%s', dossier.pk, generation_id, request.user.pk)
        raise Http404(str(exc)) from exc
    response = FileResponse(buffer, as_attachment=True, filename=generation.id_document.titre,
                            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@login_required
@require_http_methods(["GET"])
@xframe_options_sameorigin
def preview_pdf(request, num_dossier, template_id):
    dossier, template = _work_context(request, num_dossier, template_id)
    try:
        buffer = PdfPreviewService().read_preview(request.user.pk, dossier.pk, template.pk)
    except FileNotFoundError:
        raise Http404("Aucun aperçu disponible.") from None
    except PdfPreviewError as exc:
        return HttpResponse(str(exc), status=409, content_type="text/plain; charset=utf-8")
    except OSError:
        logger.exception("Lecture aperçu impossible dossier=%s template=%s utilisateur=%s", dossier.numero, template.pk, request.user.pk)
        raise Http404("Aperçu inaccessible.") from None
    response = FileResponse(buffer, content_type="application/pdf")
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["X-Content-Type-Options"] = "nosniff"
    return response
