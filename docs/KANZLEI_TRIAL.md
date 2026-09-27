# Kanzleitest und Website-Anmeldung

## Einladung für eine Kanzlei

Der Kanzleitest ist nur mit einem einmaligen Code verfügbar. Der Code ist an eine
E-Mail-Adresse gebunden und wird nur als SHA-256-Hash in der Datenbank gespeichert.
Die Kanzlei bestätigt diese Adresse mit dem bestehenden E-Mail-Code und löst
die Einladung auf `/kanzlei-test.html` ein.

Einladung auf dem API-Host ausstellen:

```sh
docker exec s2m-backend-api python -m app.scripts.issue_kanzlei_invite name@kanzlei.de
```

Den ausgegebenen Code zusammen mit
`https://www.statement2muster.com/kanzlei-test.html` in die persönliche
Einladung aufnehmen. Der Code muss innerhalb von 60 Tagen eingelöst werden;
dies ist nur die Gültigkeit der Einladung. Die 30 Tage Testzeit beginnen nach
der ersten erfolgreich verarbeiteten Datei. Das API begrenzt den Test auf
20 erfolgreich verarbeitete Auszüge und gibt die PRO-Funktionen frei.
Die Kanzlei meldet sich in der Erweiterung mit derselben E-Mail-Adresse an.

## Website-Anmeldung

Die E-Mail-Anmeldung nutzt `/api/v1/auth/request-code` und `/api/v1/auth/token`.
Google, LinkedIn und Facebook nutzen OAuth am API-Host. Ein soziales Profil
wird beim ersten Mal erst nach Bestätigung seiner E-Mail-Adresse mit dem
Statement2Muster-Konto verbunden. Spätere Anmeldungen nutzen die gespeicherte
Provider-ID. Ohne konfigurierte Provider-Zugangsdaten blendet der Web-Landing
die jeweilige Schaltfläche aus.

Für den Produktivbetrieb die Variablen aus `.env.prod.example` setzen:
`OAUTH_SESSION_SECRET` sowie ID und Secret für jeden verwendeten Anbieter.
Bei jedem Anbieter die genaue Rücksprungadresse registrieren:

```text
https://api.statement2muster.com/api/v1/auth/oauth/google/callback
https://api.statement2muster.com/api/v1/auth/oauth/linkedin/callback
https://api.statement2muster.com/api/v1/auth/oauth/facebook/callback
```

Für LinkedIn ist das Produkt „Sign In with LinkedIn using OpenID Connect“
mit den Bereichen `openid profile email` nötig. Facebook Login benötigt
Zugriff auf die E-Mail-Adresse. Wenn ein Anbieter keine E-Mail-Adresse
übermittelt, bittet die Seite um Anmeldung per E-Mail.

Vor dem Versand der Einladungen Backend und statische Seite gemeinsam
veröffentlichen, die Produktivvariablen setzen und jeden aktivierten
Anmeldeweg mit einem Testkonto vollständig durchlaufen.
