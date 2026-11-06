"""Aperçus PDF locaux, remplacement atomique et verrouillage entre workers."""

from contextlib import contextmanager
from io import BytesIO
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time

from django.conf import settings


class PdfPreviewError(Exception):
    pass


class PreviewBusyError(PdfPreviewError):
    pass


def preview_root():
    if settings.ENVIRONMENT != "dev":
        raise PdfPreviewError("Les aperçus sont réservés au développement.")
    root = Path(getattr(settings, "DOCUMENT_PREVIEW_ROOT", Path(tempfile.gettempdir()) / "agida_document_generation"))
    if (not root.is_absolute() or str(root.resolve()).startswith(("\\\\", "//"))
            or root.is_symlink() or not root.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())):
        raise PdfPreviewError("Le stockage temporaire des aperçus est mal configuré.")
    return root


def _safe_path(path):
    root = preview_root()
    if not path.resolve().is_relative_to(root.resolve()) or path == root:
        raise PdfPreviewError("Emplacement d'aperçu invalide.")
    for part in (root, *path.relative_to(root).parents, path):
        # Les parents relatifs sont vérifiés ci-dessous sous la racine.
        candidate = part if part.is_absolute() else root / part
        if candidate.is_symlink():
            raise PdfPreviewError("Lien symbolique interdit dans le stockage des aperçus.")
    return path


def preview_directory(user_id, dossier_id, template_id):
    ids = (user_id, dossier_id, template_id)
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in ids):
        raise PdfPreviewError("Identifiants de l'aperçu invalides.")
    return _safe_path(preview_root() / f"user_{user_id}" / f"dossier_{dossier_id}" / f"template_{template_id}")


@contextmanager
def _lock(directory):
    root = preview_root()
    locks = _safe_path(root / ".locks")
    locks.mkdir(parents=True, exist_ok=True)
    name = "_".join(directory.relative_to(root).parts) + ".lock"
    path = _safe_path(locks / name)
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise PreviewBusyError("Un aperçu est déjà en cours pour ce modèle. Réessayez dans un instant.") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def libreoffice_binary():
    configured = getattr(settings, "LIBREOFFICE_BINARY", None) or os.environ.get("LIBREOFFICE_BINARY")
    if configured:
        found = shutil.which(str(configured))
        if found:
            return found
        raise PdfPreviewError("LibreOffice est introuvable. Contactez l'administrateur.")
    found = shutil.which("libreoffice") or shutil.which("soffice")
    if found:
        return found
    if os.name == "nt":
        candidate = Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "LibreOffice/program/soffice.com"
        if candidate.is_file():
            return str(candidate)
    raise PdfPreviewError("LibreOffice n'est pas installé ou accessible. Contactez l'administrateur.")


def _stop_process_tree(process):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       capture_output=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()


class PdfPreviewService:
    def convert_docx_to_pdf(self, docx_path, output_dir):
        """Conversion seule, profil LibreOffice isolé pour chaque appel."""
        binary = libreoffice_binary()
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        profile = output_dir.parent / "libreoffice_profile"
        args = [binary, f"-env:UserInstallation={profile.resolve().as_uri()}", "--headless",
                "--nologo", "--nodefault", "--nofirststartwizard", "--norestore", "--quickstart=no", "--convert-to", "pdf:writer_pdf_Export",
                "--outdir", str(output_dir), str(docx_path)]
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
        try:
            timeout = float(getattr(settings, "DOCUMENT_PREVIEW_TIMEOUT", os.environ.get("DOCUMENT_PREVIEW_TIMEOUT", "60")))
            if not 0 < timeout < float("inf"):
                raise PdfPreviewError("Le délai de conversion PDF est mal configuré.")
            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options)
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                try:
                    _stop_process_tree(process)
                except (OSError, subprocess.TimeoutExpired):
                    if process.poll() is None:
                        process.kill()
                finally:
                    if process.poll() is None:
                        process.kill()
                    try:
                        process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                raise PdfPreviewError("La conversion PDF a dépassé le délai autorisé. Réessayez.") from exc
            if process.returncode:
                raise RuntimeError(f"LibreOffice code={process.returncode}, stderr={stderr[-2000:]!r}, stdout={stdout[-2000:]!r}")
            pdf = output_dir / (Path(docx_path).stem + ".pdf")
            if not pdf.is_file() or pdf.stat().st_size < 6:
                raise RuntimeError("LibreOffice n'a pas produit de PDF non vide.")
            with pdf.open("rb") as stream:
                if stream.read(5) != b"%PDF-":
                    raise RuntimeError("Le fichier produit n'est pas un PDF.")
            return pdf
        except PdfPreviewError:
            raise
        except Exception as exc:
            raise PdfPreviewError("Impossible de convertir le document en PDF. Contactez l'administrateur.") from exc

    def create_preview(self, docx_buffer, user_id, dossier_id, template_id):
        directory = preview_directory(user_id, dossier_id, template_id)
        try:
            with _lock(directory):
                directory.mkdir(parents=True, exist_ok=True)
                # L'ancien PDF reste en place tant que la nouvelle conversion échoue.
                staged = _safe_path(directory / "pending.pdf")
                try:
                    with tempfile.TemporaryDirectory(prefix="work_", dir=directory) as temporary:
                        work = Path(temporary)
                        source = work / "preview.docx"
                        try:
                            docx_buffer.seek(0)
                            source.write_bytes(docx_buffer.read())
                            pdf = self.convert_docx_to_pdf(source, work / "converted")
                            os.replace(pdf, staged)
                        finally:
                            source.unlink(missing_ok=True)
                    # Ne publie pas le nouvel aperçu avant nettoyage des intermédiaires.
                    os.replace(staged, directory / "preview.pdf")
                finally:
                    staged.unlink(missing_ok=True)
            return directory / "preview.pdf"
        except PdfPreviewError:
            raise
        except OSError as exc:
            raise PdfPreviewError("Le stockage temporaire de l'aperçu est inaccessible.") from exc

    def available(self, user_id, dossier_id, template_id):
        return _safe_path(preview_directory(user_id, dossier_id, template_id) / "preview.pdf").is_file()

    def read_preview(self, user_id, dossier_id, template_id):
        directory = preview_directory(user_id, dossier_id, template_id)
        with _lock(directory):
            # Un buffer évite de garder un PDF verrouillé par Windows pendant l'iframe.
            return BytesIO(_safe_path(directory / "preview.pdf").read_bytes())


def clean_previews(max_age_seconds=7200):
    root = preview_root()
    if not root.exists():
        return 0
    cutoff = time.time() - max_age_seconds
    removed = 0
    for directory in root.glob("user_*/dossier_*/template_*"):
        if not all(re.fullmatch(prefix + r"[1-9][0-9]*", name) for prefix, name in
                   zip(("user_", "dossier_", "template_"), directory.relative_to(root).parts)):
            continue
        _safe_path(directory)
        try:
            with _lock(directory):
                entries = [directory, *directory.rglob("*")]
                if any(entry.is_symlink() for entry in entries):
                    continue
                if max(entry.stat().st_mtime for entry in entries) < cutoff:
                    # Cible absolue vérifiée sous la racine avant suppression récursive.
                    target = _safe_path(directory).resolve()
                    if not target.is_relative_to(root.resolve()) or target == root.resolve():
                        raise PdfPreviewError("Cible de nettoyage invalide.")
                    shutil.rmtree(target)
                    removed += 1
                    for parent in (directory.parent, directory.parent.parent):
                        try:
                            _safe_path(parent).rmdir()
                        except OSError:
                            pass  # Autres templates/dossiers encore présents.
        except (PreviewBusyError, FileNotFoundError):
            continue
    return removed
