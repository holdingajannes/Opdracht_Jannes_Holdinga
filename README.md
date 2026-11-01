# Sales pipeline module, CLIENTNAME portal

Prototype van de sales pipeline module uit de intern challenge van Yield Group.
De module dekt het traject van klantaanvraag tot order:
**Proposal → Quotation → Approval → Order**.

## Opstarten

Vereist: Python 3.9 of hoger.

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    python seed.py      # eenmalig: testbedrijven en testgebruikers
    python main.py      # start de app op http://127.0.0.1:5001

Herinneringen voor open offertes (in productie dagelijks via een geplande taak):

    python remind.py

## Testaccounts

Wachtwoord voor alle accounts: `test123`

| Rol | E-mail | Toegang |
|---|---|---|
| Klant | klant@devries.nl | Aanvragen van Bouwbedrijf De Vries |
| Klant | klant@jansen.nl | Aanvragen van Staalhandel Jansen |
| Verkoopingenieur | sanne@clientname.nl | Gekoppeld aan De Vries |
| Verkoopingenieur | mark@clientname.nl | Gekoppeld aan Jansen |
| Beheerder | admin@clientname.nl | Alles, plus rapportages en beheer |

## Testbestanden

In de map `testbestanden/` staan fictieve documenten om de workflow te testen:

| Bestand | Gebruik |
|---|---|
| testofferte_v1.pdf | Eerste offerte: OFF-2026-0042, EUR 48.500, 14 weken |
| testofferte_v2.pdf | Tweede versie: EUR 46.900, 12 weken |
| testtekening.pdf | Bijlage bij de offerte |

## Demo doorlopen

Tip: gebruik een normaal en een incognitovenster, zodat klant en verkoopingenieur
tegelijk ingelogd kunnen zijn.

1. **Aanvraag (klant@devries.nl).** Klik op Nieuwe aanvraag en vul de specificaties in:
   enkelligger, 2m, 5 ton kettingtakel, snelheden 4 / 20 / 32, kraanbaan 2 x 40 m,
   overspanning 18 m, hijshoogte 8 m, 400V, radiografisch, binnen.
   Indienen zonder verplichte velden lukt niet. Status: *Nieuw*.
2. **Offerte (sanne@clientname.nl).** Upload `testofferte_v1.pdf` (referentie OFF-2026-0042,
   prijs 48500, EUR, 14 weken, geldig tot 01-12-2026) met `testtekening.pdf` als bijlage.
   Status: *Offerte verstuurd*; de klant krijgt een e-mail.
3. **Wijzigingen (klant).** Bekijk de offerte en bijlage. Wijzigingen vragen zonder reden
   wordt geweigerd; met reden lukt het en krijgt Sanne een e-mail. Plaats een opmerking.
4. **Versie 2 (Sanne).** Reageer op de opmerking en upload `testofferte_v2.pdf`
   (46900, 12 weken). Versie 1 blijft zichtbaar onder Eerdere versies.
5. **Goedkeuren (klant).** De klant keurt versie 2 goed.
6. **Order (Sanne).** Omzetten naar order: ORD-00001, status *Order aangemaakt*.
   Het uploadformulier verdwijnt. Bekijk Mijn meldingen.
7. **Toegang (mark@clientname.nl).** Mark ziet de aanvraag van De Vries niet;
   `/proposals/1` direct openen geeft een 404.
8. **Beheer (admin@clientname.nl).** Rapportages, Audit, E-mails en Koppelingen.
   Koppel Mark aan De Vries: hij ziet de aanvraag nu wel. Zet het daarna terug.
   Probeer de filters op het overzicht.
9. **Herinneringen (optioneel).** Zorg dat er een offerte openstaat, zet in
   `notifications.py` tijdelijk `REMINDER_DAYS = 0` en `MANAGER_DAYS = 0` en klik als
   admin op Herinneringen nu controleren. Een tweede klik verstuurt niets dubbel.
   Zet de waarden daarna terug op 3 en 7.

Opnieuw beginnen met een lege database: stop de app, verwijder `pipeline.db` en de
bestanden in `uploads/`, en draai `python seed.py` opnieuw.

## Wat er gebouwd is

**Klant**
- Gestructureerd aanvraagformulier met alle kraanspecificaties (verplichte velden, controle in browser en server)
- Overzicht van eigen aanvragen met status
- Offerte bekijken, inclusief PDF en bijlagen
- Goedkeuren, afwijzen (met reden) of wijzigingen vragen (met reden)
- Opmerkingen, volledige geschiedenis en eigen meldingen

**Verkoopingenieur**
- Ziet alleen aanvragen van gekoppelde bedrijven
- Overzicht met filters op status, bedrijf en leeftijd
- Offerte uploaden met referentie, prijs, valuta, levertijd, geldigheid, PDF en bijlagen
- Nieuwe versies uploaden; oudere versies blijven bewaard en zichtbaar
- Opmerkingen plaatsen
- Goedgekeurde offerte met één klik omzetten naar een order

**Beheerder**
- Verkoopingenieurs aan bedrijven koppelen
- Rapportages: conversieratio, gemiddelde tijd tot offerte, gemiddelde reactietijd klant,
  werkvoorraad per verkoopingenieur, aanvragen per status
- Auditoverzicht van alle acties
- Overzicht van alle verstuurde e-mails, met handmatige herinneringscontrole

**Meldingen**
- Offerte geüpload of bijgewerkt → klant
- Goedgekeurd, afgewezen of wijzigingen gevraagd → verkoopingenieur
- Offerte 3 dagen open → herinnering verkoopingenieur
- Offerte 7 dagen open → melding manager
- Elke herinnering gaat maar één keer per offerteversie

## Projectstructuur

    main.py            Routes, toegangscontrole en workflowlogica
    db.py              Databaseschema (SQLite) en verbinding
    notifications.py   E-mailmeldingen en herinneringen
    seed.py            Testdata
    remind.py          Script voor dagelijkse herinneringen
    templates/         HTML-pagina's (Jinja)
    uploads/           Geüploade offertes en bijlagen
    testbestanden/     Fictieve PDF's voor de demo

## Aannames en ontwerpkeuzes

- **Zelfstandig prototype.** Het bestaande CLIENTNAME-portaal was niet beschikbaar.
  De module heeft daarom een eigen login en een eenvoudige `orders`-tabel die de rol
  van het bestaande ordersysteem speelt. In de echte situatie sluit de module aan op
  de bestaande gebruikers en orders.
- **E-mail via een outbox.** E-mails worden opgeslagen in de tabel `email_outbox` en
  zijn te bekijken in het portaal. Alle verzending loopt via één functie (`send_email`),
  zodat koppelen aan een echte mailserver op één plek gebeurt.
- **Conversieratio** = goedgekeurde aanvragen / (goedgekeurd + afgewezen).
  Lopende aanvragen tellen niet mee.
- **Statusovergangen worden afgedwongen.** Een klant kan alleen beslissen als er een
  offerte klaarstaat; na goedkeuring kan er geen nieuwe versie meer bij; alleen een
  goedgekeurde offerte kan een order worden; per aanvraag bestaat maximaal één order.
- **Toegang wordt op de server gecontroleerd**, ook voor bestanden. Wie een aanvraag
  niet mag zien, krijgt een 404, ook bij het direct intypen van een URL.
- **Tijden** worden in UTC opgeslagen en in Nederlandse tijd getoond.

## Wat ik in productie anders zou doen

- Aansluiten op het bestaande portaal (gebruikers, login, ordersysteem)
- Echte e-mailverzending via SMTP of een maildienst, buiten de databasetransactie
- Een productieserver (bijv. Gunicorn) en een database als PostgreSQL
- Geheime sleutel en instellingen uit omgevingsvariabelen in plaats van in de code
- Bestandsopslag in cloudopslag in plaats van een lokale map
- Geautomatiseerde tests voor de workflow en de toegangsregels
- CSRF-bescherming op formulieren (bijv. met Flask-WTF)