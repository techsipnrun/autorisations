import smtplib
from email.mime.text import MIMEText

SMTP_SERVER = "smtp-reunion.pnrun.local"
FROM_INTERNAL = "louis.calu@reunion-parcnational.fr"
TO_INTERNAL = "louis.calu@reunion-parcnational.fr"   

body = "Salut Raph"

def try_send(port, use_starttls=False):
    print(f"\n--- Test envoi sur port {port} (STARTTLS={use_starttls}) ---")
    try:
        with smtplib.SMTP(SMTP_SERVER, port, timeout=10) as server:
            server.set_debuglevel(1)
            code, hello = server.ehlo()
            print("EHLO code:", code, "|", hello.decode(errors="ignore"))

            if use_starttls:
                if server.has_extn("starttls"):
                    server.starttls()
                    server.ehlo()
                else:
                    print("STARTTLS non supporté, on continue sans TLS.")

            msg = MIMEText(body)
            msg["From"] = FROM_INTERNAL
            msg["To"] = TO_INTERNAL
            msg["Subject"] = "Mail automatique du bon vieux Louis"

            server.sendmail(FROM_INTERNAL, [TO_INTERNAL], msg.as_string())
            print("✅ Envoi OK sur port", port)
    except Exception as e:
        print("❌ Echec sur port", port, ":", e)

# 1) Port 25 sans AUTH
try_send(25, use_starttls=False)

# 2) Port 587, tenter STARTTLS si dispo, sans AUTH (si AUTH non supporté)
# try_send(587, use_starttls=True)
