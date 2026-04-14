# Ausleihsystem - Datenbank Models

**Stand:** 18.03.2026  
**Backend:** Django 5.x mit PostgreSQL

---

## Übersicht: 15 Models

| Nr. | Model | Zweck | Wichtige Felder |
|-----|-------|-------|-----------------|
| 1 | **SystemEinstellung** | Globale Hardware-Config | `schluessel`, `wert`, `geaendert_von` |
| 2 | **ErlaubteEmailDomain** | E-Mail Domains für Registrierung | `domain`, `aktiv` |
| 3 | **Benutzer** | Benutzerverwaltung | `email`, `rolle`, `rfid_karte` |
| 4 | **TokenPair** | JWT Session-Management | `access_token_jti`, `revoked` |
| 5 | **BenutzerKommentar** | Interne Benutzer-Kommentare | `benutzer`, `kommentar` |
| 6 | **BenutzerWarenkategorieBerechtigung** | Spezielle Kategorie-Berechtigungen | `benutzer`, `kategorie` |
| 7 | **VerbleibOrt** | Ausleih-Ziele (Schränke, Labore) | `name`, `ist_lager` |
| 8 | **Warenkategorie** | Artikel-Gruppierung | `name`, `erlaubte_verbleib_orte` |
| 9 | **KategorieVerbleibRegel** | Berechtigungen pro Kategorie/Ort | `minimale_rolle`, `gesperrt` |
| 10 | **Ware** | Die eigentlichen Gegenstände | `name`, `rfid_tag`, `schranknummer` |
| 11 | **Ausleihe** | Ausleihvorgänge | `ware`, `benutzer`, `status` |
| 12 | **AusleiheHistorie** | Unveränderliche Historie | `ausleihe`, `aktion`, `zeitpunkt` |
| 13 | **AusleiheLog** | Audit-Log mit IP | `aktion`, `ip_address`, `details` |
| 14 | **AntennenEinstellung** | RFID-Config pro Labor | `port`, `baudrate`, `geraete_params` |
| 15 | **Schadensmeldung** | Schadens-Meldungen | `ware`, `quittiert`, `quittierer` |

---

## 1. SystemEinstellung

**Zweck:** Globale Hardware-Konfiguration für alle Frontends

**Wichtige Felder:**
- `schluessel` (CharField, unique) - z.B. 'antenna_port', 'cardreader_port'
- `wert` (TextField) - Der eigentliche Wert
- `beschreibung` (TextField, optional)
- `geaendert_von` (FK → Benutzer, optional)
- `erstellt_am`, `aktualisiert_am` (DateTime)

**Verwendung:**
- AntennaSettings.tsx: Speichert/ändert Ports
- App.tsx: Lädt beim Start die aktuellen Werte

**Standardwerte:**
```
antenna_port = /dev/ttyUSB0
antenna_baudrate = 115200
cardreader_port = /dev/ttyUSB0
cardreader_baudrate = 9600
```

**Methoden:**
- `get_value(schluessel, default=None)` - Holt Wert oder Default
- `set_value(schluessel, wert, beschreibung='')` - Setzt Wert

---

## 2. ErlaubteEmailDomain

**Zweck:** Steuerung, wer sich registrieren darf

**Wichtige Felder:**
- `domain` (CharField, unique) - z.B. '@th-koeln.de'
- `beschreibung` (CharField, optional)
- `aktiv` (BooleanField, default=True)

**Verwendung:**
- RegisterForm.tsx: Prüft E-Mail-Endung
- LoginForm.tsx: Validierung

**Standardwerte (werden bei erster Migration angelegt):**
- @th-koeln.de
- @smail.th-koeln.de

---

## 3. Benutzer

**Zweck:** Zentrale Benutzerverwaltung (eigenes System statt Django-Auth)

**Wichtige Felder:**
- `email` (CharField, unique)
- `vorname`, `nachname` (CharField)
- `passwort_hash` (CharField) - bcrypt Hash
- `rolle` (CharField) - Student/Mitarbeiter/Laborleiter/Admin
- `rfid_karte` (CharField, unique, optional) - Für Karten-Login
- `letzter_login`, `letzte_ip`, `letztes_geraet`
- `aktiv` (BooleanField, default=True)

**Eigenschaften:**
- Eigene User-Tabelle für mehr Flexibilität
- Login per E-Mail/Passwort ODER RFID-Karte
- Rollenbasierte Berechtigungen

**Methoden:**
- `hat_rolle(minimale_rolle)` - Prüft Rollenhierarchie
- `kann_ware_ausleihen(ware)` - Prüft Berechtigung
- `get_erlaubte_verbleib_orte()` - Wo darf dieser User ausleihen?

---

## 4. TokenPair

**Zweck:** JWT Session-Management mit Widerruf

**Wichtige Felder:**
- `access_token_jti` (CharField) - JWT ID für Access Token
- `refresh_token_jti` (CharField) - JWT ID für Refresh Token
- `benutzer` (FK → Benutzer)
- `erstellt_am`, `letzte_verwendung`
- `revoked` (BooleanField) - Widerrufen?
- `revoked_at`, `revoked_reason`
- `device_info`, `ip_address` - Für Audit

**Verwendung:**
- Login: Erstellt neues Token-Paar
- API-Calls: Prüft Access Token
- Logout: Setzt revoked=True

---

## 5. BenutzerKommentar

**Zweck:** Interne Kommentare zu Benutzern (nur für Mitarbeiter+)

**Wichtige Felder:**
- `benutzer` (FK → Benutzer)
- `kommentar` (TextField)
- `erstellt_von` (FK → Benutzer)
- `erstellt_am`

**Status:** Vorhanden aber noch nicht im Frontend implementiert

---

## 6. BenutzerWarenkategorieBerechtigung

**Zweck:** Spezielle Berechtigungen für bestimmte Kategorien

**Wichtige Felder:**
- `benutzer` (FK → Benutzer)
- `kategorie` (FK → Warenkategorie)
- `darf_ausleihen` (BooleanField)
- `max_leihdauer_tage` (IntegerField, optional)
- `gueltig_ab`, `gueltig_bis` (DateTime, optional)

**Verwendung:**
- Noch nicht aktiv
- Geplant: Studenten für besondere Kategorien freischalten

---

## 7. VerbleibOrt

**Zweck:** Orte, wo ausgeliehene Waren verbleiben

**Wichtige Felder:**
- `name` (CharField, unique) - z.B. "Schrank A1"
- `beschreibung` (TextField, optional)
- `ist_lager` (BooleanField) - Ist das der Haupt-Lagerort?
- `aktiv` (BooleanField)

**Verwendung:**
- BorrowView.tsx: Auswahl bei Ausleihe
- KategorieVerbleibRegel: Berechtigungen pro Ort

---

## 8. Warenkategorie

**Zweck:** Gruppierung von Waren

**Wichtige Felder:**
- `name` (CharField, unique)
- `beschreibung` (TextField, optional)
- `erlaubte_verbleib_orte` (ManyToMany → VerbleibOrt)
- `aktiv` (BooleanField)

**Verwendung:**
- Dashboard.tsx: Filterung nach Kategorien
- ItemDialog.tsx: Zuordnung bei Erstellung
- KategorieVerbleibRegel: Berechtigungen

---

## 9. KategorieVerbleibRegel

**Zweck:** Regelt wer welche Kategorie wohin ausleihen darf

**Wichtige Felder:**
- `kategorie` (FK → Warenkategorie)
- `verbleib_ort` (FK → VerbleibOrt)
- `minimale_rolle` (CharField) - Student/Mitarbeiter/Laborleiter/Admin
- `gesperrt` (BooleanField)

**Beispiel:**
- Mikroskope → Labor 3.12: nur Laborleiter+
- Kabel → Schrank A1: Student+

---

## 10. Ware

**Zweck:** Die eigentlichen ausleihbaren Gegenstände

**Wichtige Felder:**
- `name` (CharField)
- `beschreibung` (TextField, optional)
- `kategorien` (ManyToMany → Warenkategorie)
- `rfid_tag` (CharField, unique, optional) - EPC für RFID
- `schranknummer` (CharField, optional) - Physische Lagerung
- `labor` (FK → Labor, optional)
- `ist_ausgeliehen` (BooleanField)
- `ist_gesperrt` (BooleanField)
- `sperr_grund` (TextField, optional)
- `aktiv` (BooleanField)

**Methoden:**
- `ist_verfuegbar()` - Prüft Verfügbarkeit
- `get_erlaubte_verbleib_orte(rolle)` - Wo darf diese Rolle hin?

---

## 11. Ausleihe

**Zweck:** Ausleihvorgänge (aktiv und historisch)

**Wichtige Felder:**
- `ware` (FK → Ware)
- `benutzer` (FK → Benutzer) - Wer hat ausgeliehen
- `verantwortlicher` (FK → Benutzer, optional) - Wer hat bearbeitet
- `ausgeliehen_am` (DateTime)
- `geplante_rueckgabe` (Date, optional)
- `tatsaechliche_rueckgabe` (DateTime, optional)
- `verbleib_ort` (FK → VerbleibOrt)
- `status` (CharField): `aktiv`, `rueckgabe_beantragt`, `abgeschlossen`, `ueberfaellig`
- `zweck` (TextField, optional)

**Methoden:**
- `ist_ueberfaellig()` - Prüft Fristüberschreitung
- `rueckgabe_beantragen()` - Student beantragt Rückgabe
- `quittiere_rueckgabe(zustand, kommentar, genehmigt_von)` - Mitarbeiter quittiert
- `verlaengern(neues_datum, genehmigt_von)` - Verlängerung

---

## 12. AusleiheHistorie

**Zweck:** Unveränderliche Kopie für Langzeitarchivierung

**Wichtige Felder:**
- `ausleihe` (FK → Ausleihe)
- `aktion` (CharField) - ausleihe, rueckgabe, verlaengerung
- `zeitpunkt` (DateTime)
- `benutzer_id`, `benutzer_name`, `benutzer_rolle` - Dupliziert
- `ware_id`, `ware_name`, `ware_beschreibung` - Dupliziert
- `verbleib_ort_id`, `verbleib_ort_name` - Dupliziert
- `zustand`, `kommentar`
- `genehmigt_von_id`, `genehmigt_von_name` - Wer hat quittiert

**Besonderheit:** Alle Daten werden dupliziert (nicht normalisiert), damit sie auch nach Löschung der Ware/Benutzer erhalten bleiben.

---

## 13. AusleiheLog

**Zweck:** Detailliertes Audit-Log aller Aktionen

**Wichtige Felder:**
- `benutzer`, `benutzer_id_logged` - Wer hat Aktion ausgeführt
- `ware`, `ware_id_logged`
- `ausleihe`
- `aktion` (CharField) - LOGIN, AUSLEIHE, RUECKGABE, etc.
- `methode` (CharField) - api, rfid, manuell
- `details` (JSONField)
- `ip_address`, `device_info` - Für Audit

**Verwendung:**
- Alle API-Calls loggen automatisch
- Nachvollziehbarkeit wer wann was gemacht hat

---

## 14. AntennenEinstellung

**Zweck:** RFID-Antennen-Konfigurationen pro Labor

**Wichtige Felder:**
- `name` (CharField) - z.B. "Hauptlabor Station 1"
- `labor_id` (UUID, optional)
- `port` (CharField, default='/dev/ttyUSB0')
- `baudrate` (IntegerField, default=115200)
- `rf_power` (IntegerField, default=30)
- `work_mode` (IntegerField, default=0)
- `geraete_params` (JSONField) - Alle anderen Parameter
- `ist_aktiv` (BooleanField)

**Status:** Vorhanden aber noch nicht im Frontend implementiert

---

## 15. Schadensmeldung

**Zweck:** Meldung und Quittierung von Schäden

**Wichtige Felder:**
- `ware` (FK → Ware)
- `ausleihe` (FK → Ausleihe, optional)
- `beschreibung` (TextField) - Schadensbeschreibung
- `rueckgeber` (FK → Benutzer, optional) - Wer hat gemeldet
- `erstellt_am` (DateTime)
- `quittiert` (BooleanField)
- `quittierer` (FK → Benutzer, optional) - Wer hat quittiert
- `quittiert_am` (DateTime, optional)
- `quittierer_beschreibung` (TextField, optional) - Ergänzung durch Mitarbeiter

**Ablauf:**
1. Student meldet Schaden bei Rückgabe
2. Mitarbeiter quittiert in SchadensmeldungDialog.tsx
3. Mitarbeiter kann Beschreibung ergänzen/ändern

---

## Beziehungen zwischen Models

```
Benutzer ────┬───> TokenPair
             ├───> BenutzerKommentar
             ├───> BenutzerWarenkategorieBerechtigung ──> Warenkategorie
             ├───> Ausleihe ──> Ware
             │       └───> AusleiheHistorie
             │       └───> Schadensmeldung
             └───> AusleiheLog

Warenkategorie ────┬───> KategorieVerbleibRegel ──> VerbleibOrt
                   └───> Ware

SystemEinstellung (global, keine Beziehungen)
AntennenEinstellung (eigenständig)
ErlaubteEmailDomain (eigenständig)
```

---

## Wichtige API-Endpunkte pro Model

| Model | Endpunkte |
|-------|-----------|
| Benutzer | /login/, /register/, /me/, /benutzer/ |
| Ware | /waren/, /waren/<id>/ |
| Ausleihe | /ausleihen/, /ausleihen/<id>/, /borrow/, /return/ |
| Warenkategorie | /kategorien/ |
| VerbleibOrt | /verbleib-orte/ |
| SystemEinstellung | /system-einstellungen/, /system-einstellungen-oeffentlich/ |
| Schadensmeldung | /schadensmeldungen/, /schadensmeldungen/offen/ |

---

## Migrationen

Alle Models sind in der initialen Migration `0001_initial.py` enthalten.  
Keine weiteren Migrationen nötig (außer bei zukünftigen Änderungen).

---

**Generiert:** 18.03.2026  
**Datei:** `DATENBANK_MODELS.md`
