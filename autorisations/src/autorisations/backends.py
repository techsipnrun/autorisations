# Backend Custom (sans vérifier le certificat) pour l'envoi des mails
import ssl
from django.core.mail.backends.smtp import EmailBackend

class UnsafeEmailBackend(EmailBackend):
    """
    Backend SMTP qui fait STARTTLS avec un contexte SSL non vérifié
    (pour serveurs avec certificat auto-signé / CA interne non installée).
    """
    def open(self):
        # Assure qu'on utilise bien notre contexte, même si Django ignore ssl_context
        self.ssl_context = ssl._create_unverified_context()
        return super().open()
