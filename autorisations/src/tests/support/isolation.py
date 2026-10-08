"""Isolation partagée par les lanceurs Django et pytest."""
from contextlib import ExitStack
import os
import socket
from unittest.mock import patch


def isoler_environnement():
    stack = ExitStack()
    # Certains modules applicatifs chargent eux-mêmes un .env à l'import.
    stack.enter_context(patch("dotenv.load_dotenv", return_value=False))
    stack.enter_context(patch("dotenv.dotenv_values", return_value={}))
    valeurs = {"NOTIF_PROD": "false", "EMAIL_NOTIF_TEST": "notifications@example.test"}
    externe = os.getenv("RUN_LIVE_API_TESTS") == "1"
    if not externe:
        valeurs.update({
            "API_URL": "https://dn.example.test/graphql",
            "API_TOKEN_BOITE_AUTO": "jeton-tests",
            "DM_API_URL": "https://dm.example.test/",
            "DM_API_URL_PROD": "https://dm-prod.example.test/",
            "DM_USERNAME": "tests", "DM_PASSWORD": "tests",
            "DM_CLIENT_ID": "tests", "DM_CLIENT_SECRET": "tests",
        })
    valeurs["NAS_ROOT"] = r"\\nas-tests.invalid\share"
    stack.enter_context(patch.dict(os.environ, valeurs))

    if not externe and os.getenv("RUN_DB_TESTS") != "1":
        def verifier_hote(hote):
            if hote not in (None, "localhost", "127.0.0.1", "::1", b"localhost", b"127.0.0.1", b"::1"):
                raise RuntimeError(f"Accès réseau externe interdit pendant les tests : {hote!r}")

        getaddrinfo = socket.getaddrinfo
        connect = socket.socket.connect
        connect_ex = socket.socket.connect_ex

        def resolution(hote, *args, **kwargs):
            verifier_hote(hote)
            return getaddrinfo(hote, *args, **kwargs)

        def connexion(sock, adresse):
            verifier_hote(adresse[0] if isinstance(adresse, tuple) else adresse)
            return connect(sock, adresse)

        def connexion_ex(sock, adresse):
            verifier_hote(adresse[0] if isinstance(adresse, tuple) else adresse)
            return connect_ex(sock, adresse)

        stack.enter_context(patch("socket.getaddrinfo", resolution))
        stack.enter_context(patch("socket.socket.connect", connexion))
        stack.enter_context(patch("socket.socket.connect_ex", connexion_ex))
    return stack
