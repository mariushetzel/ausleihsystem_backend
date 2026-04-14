"""
Ausleihsystem - Vollständiges Datenbankmodell
Mit dupliziertem Benutzer-System für eigenständige Funktion
"""

import uuid
from django.db import models
from django.utils import timezone
from datetime import timedelta


# =============================================================================
# SYSTEM-EINSTELLUNGEN (Global für alle Benutzer)
# =============================================================================

class SystemEinstellung(models.Model):
    """
    Globale Systemeinstellungen für Hardware-Konfiguration.
    Diese Einstellungen gelten für alle Benutzer und Frontends.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Schlüssel für die Einstellung (z.B. 'antenna_port', 'cardreader_port')
    schluessel = models.CharField(max_length=100, unique=True)
    wert = models.TextField()
    beschreibung = models.TextField(blank=True)
    
    # Wer hat die Einstellung geändert
    geaendert_von = models.ForeignKey('Benutzer', on_delete=models.SET_NULL,
                                      null=True, blank=True, related_name='geaenderte_einstellungen')
    
    # Audit
    erstellt_am = models.DateTimeField(auto_now_add=True)
    aktualisiert_am = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = "System-Einstellungen"
        ordering = ['schluessel']
    
    def __str__(self):
        return f"{self.schluessel}: {self.wert}"
    
    @classmethod
    def get_value(cls, schluessel, default=None):
        """Holt einen Einstellungswert oder gibt den Default zurück."""
        try:
            einstellung = cls.objects.get(schluessel=schluessel)
            return einstellung.wert
        except cls.DoesNotExist:
            return default
    
    @classmethod
    def set_value(cls, schluessel, wert, beschreibung=''):
        """Setzt einen Einstellungswert."""
        einstellung, created = cls.objects.get_or_create(
            schluessel=schluessel,
            defaults={'wert': wert, 'beschreibung': beschreibung}
        )
        if not created:
            einstellung.wert = wert
            if beschreibung:
                einstellung.beschreibung = beschreibung
            einstellung.save()
        return einstellung


# =============================================================================
# ERLAUBTE E-MAIL DOMAINS
# =============================================================================

class ErlaubteEmailDomain(models.Model):
    """
    Liste der erlaubten E-Mail-Domains für neue Benutzer.
    Nur Benutzer mit E-Mail-Adressen, die auf diese Domains enden, können sich registrieren.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    domain = models.CharField(max_length=100, unique=True, help_text="z.B. @th-koeln.de oder @smail.th-koeln.de")
    beschreibung = models.CharField(max_length=255, blank=True, help_text="Optional: Beschreibung der Domain")
    aktiv = models.BooleanField(default=True)
    erstellt_am = models.DateTimeField(auto_now_add=True)
    aktualisiert_am = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = "Erlaubte E-Mail Domains"
        ordering = ['domain']
    
    def __str__(self):
        return self.domain


# =============================================================================
# BENUTZER-MODUL (dupliziert für eigenständige Funktion)
# =============================================================================

class Benutzer(models.Model):
    """
    Duplizierte Benutzer-Tabelle für eigenständiges Ausleihsystem.
    Später kann dies durch Fremdschlüssel zum externen System ersetzt werden.
    """
    ROLLEN_CHOICES = [
        ('Student', 'Student'),
        ('Mitarbeiter', 'Mitarbeiter'),
        ('Laborleiter', 'Laborleiter'),
        ('Admin', 'Admin'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(max_length=254, unique=True)
    passwort_hash = models.CharField(max_length=255)
    vorname = models.CharField(max_length=100)
    nachname = models.CharField(max_length=100)
    
    # Rolle für Berechtigungen
    rolle = models.CharField(max_length=50, choices=ROLLEN_CHOICES, default='Student')
    
    # RFID für Login am Ausleihsystem
    rfid_karte = models.CharField(max_length=50, unique=True, null=True, blank=True)
    
    # Optional: Verknüpfung zu Labor (für Laborleiter-Berechtigungen)
    labor_id = models.UUIDField(null=True, blank=True, help_text="Für Laborleiter: Verwaltetes Labor")
    
    # Status
    aktiv = models.BooleanField(default=True)
    letzter_login = models.DateTimeField(null=True, blank=True)
    
    # E-Mail-Verifizierung
    bestaetigung_token = models.CharField(max_length=255, blank=True)
    token_erstellt_am = models.DateTimeField(null=True, blank=True)
    
    # Audit
    erstellt_am = models.DateTimeField(auto_now_add=True)
    aktualisiert_am = models.DateTimeField(auto_now=True)
    
    # Sync-Felder (für spätere Integration)
    scope = models.CharField(max_length=20, default='local')
    origin_server_id = models.CharField(max_length=100, blank=True)
    sync_version = models.IntegerField(default=1)

    class Meta:
        verbose_name_plural = "Benutzer"
        indexes = [
            models.Index(fields=['aktiv', 'email']),
            models.Index(fields=['rfid_karte', 'aktiv']),
            models.Index(fields=['rolle', 'aktiv']),
            models.Index(fields=['labor_id', 'aktiv']),
        ]

    def __str__(self):
        return f"{self.vorname} {self.nachname} ({self.rolle})"
    
    @property
    def rolle_level(self):
        """Gibt das Level der Rolle zurück (1-4)"""
        levels = {'Student': 1, 'Mitarbeiter': 2, 'Laborleiter': 3, 'Admin': 4}
        return levels.get(self.rolle, 1)
    
    def hat_mindestens_rolle(self, min_rolle):
        """Prüft ob Benutzer mindestens die angegebene Rolle hat"""
        min_level = {'Student': 1, 'Mitarbeiter': 2, 'Laborleiter': 3, 'Admin': 4}.get(min_rolle, 4)
        return self.rolle_level >= min_level
    
    def darf_quittieren(self):
        """Prüft ob Benutzer Rückgaben quittieren darf (Mitarbeiter+)"""
        return self.rolle_level >= 2
    
    def darf_antennen_einstellen(self):
        """Prüft ob Benutzer Antennen-Einstellungen ändern darf (Mitarbeiter+)"""
        return self.rolle_level >= 2
    
    def darf_waren_verwalten(self):
        """Prüft ob Benutzer auf Warenverwaltung zugreifen darf (Mitarbeiter+)"""
        return self.rolle_level >= 2
    
    def darf_alles_verwalten(self):
        """Prüft ob Benutzer alles verwalten darf (Laborleiter+)"""
        return self.rolle_level >= 3
    
    def hat_passwort(self):
        """Prüft ob der Benutzer ein echtes Passwort gesetzt hat (nicht nur Karten-Login)"""
        if not self.passwort_hash:
            return False
        # Prüfen ob es das temporäre "Karten-only" Passwort ist
        # Da bcrypt verschiedene Hashes erzeugt, müssen wir verify verwenden
        import bcrypt
        try:
            is_temp = bcrypt.checkpw('__KARTEN_LOGIN_ONLY__'.encode(), self.passwort_hash.encode())
            return not is_temp
        except:
            return True  # Wenn Verify fehlschlägt, gehen wir von echtem Passwort aus


class TokenPair(models.Model):
    """
    JWT Token-Verwaltung mit Rotation und Widerruf.
    Speichert alle aktiven Token-Sessions eines Benutzers.
    """
    REVOKE_REASONS = [
        ('logout', 'Logout'),
        ('stolen', 'Gestohlen'),
        ('expired', 'Abgelaufen'),
        ('refreshed', 'Erneuert'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    benutzer = models.ForeignKey(Benutzer, on_delete=models.CASCADE, related_name='token_pairs')
    
    # Token-Familie für Rotation
    family_id = models.UUIDField(default=uuid.uuid4)
    pair_id = models.UUIDField(default=uuid.uuid4, unique=True)
    
    # Access Token (kurzlebig)
    access_token_jti = models.CharField(max_length=255, unique=True)
    access_token_expires = models.DateTimeField()
    
    # Refresh Token (langfristig, gehasht gespeichert)
    refresh_token_jti = models.CharField(max_length=255, unique=True)
    refresh_token_hash = models.CharField(max_length=255)
    refresh_token_expires = models.DateTimeField()
    
    # Geräteinformationen für Audit
    device_info = models.CharField(max_length=500, blank=True)
    ip_address = models.CharField(max_length=45, blank=True)
    
    # Widerruf
    revoked = models.BooleanField(default=False)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(max_length=20, choices=REVOKE_REASONS, blank=True)
    
    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "Token Pairs"
        indexes = [
            models.Index(fields=['benutzer', 'revoked']),
            models.Index(fields=['access_token_jti']),
            models.Index(fields=['refresh_token_jti']),
            models.Index(fields=['family_id', 'revoked']),
        ]


class BenutzerKommentar(models.Model):
    """
    Kommentare zu Benutzern (z.B. für Probleme, Schulungen, etc.)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    benutzer = models.ForeignKey(Benutzer, on_delete=models.CASCADE, related_name='kommentare')
    erstellt_von = models.ForeignKey(Benutzer, on_delete=models.SET_NULL, 
                                     null=True, related_name='erstellte_kommentare')
    kommentar = models.CharField(max_length=2000)
    
    # Status
    aktiv = models.BooleanField(default=True)
    
    # Audit
    erstellt_am = models.DateTimeField(auto_now_add=True)
    aktualisiert_am = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Benutzer-Kommentare"
        ordering = ['-erstellt_am']


class BenutzerWarenkategorieBerechtigung(models.Model):
    """
    Spezielle Berechtigungen für bestimmte Warenkategorien.
    Z.B.: Laser-Cutter-Schulung, 3D-Drucker-Einweisung, etc.
    """
    BERECHTIGUNGS_TYP = [
        ('kurs', 'Kurs absolviert'),
        ('manuell', 'Manuell erteilt'),
        ('admin', 'Admin-Entscheidung'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    benutzer = models.ForeignKey(Benutzer, on_delete=models.CASCADE, 
                                 related_name='warenkategorie_berechtigungen')
    kategorie_id = models.UUIDField()  # Referenz auf Warenkategorie
    
    # Zeitliche Begrenzung (z.B. Schulung läuft ab)
    berechtigt_seit = models.DateTimeField(auto_now_add=True)
    berechtigt_bis = models.DateTimeField(null=True, blank=True)  # NULL = permanent
    
    # Wer hat berechtigt
    berechtigt_von = models.ForeignKey(Benutzer, on_delete=models.SET_NULL,
                                       null=True, related_name='vergebene_kategorie_berechtigungen')
    
    berechtigungs_typ = models.CharField(max_length=20, choices=BERECHTIGUNGS_TYP, default='manuell')
    
    # Status
    aktiv = models.BooleanField(default=True)
    
    # Audit
    erstellt_am = models.DateTimeField(auto_now_add=True)
    aktualisiert_am = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Warenkategorie-Berechtigungen"
        unique_together = ['benutzer', 'kategorie_id']
        indexes = [
            models.Index(fields=['benutzer', 'aktiv']),
            models.Index(fields=['kategorie_id', 'aktiv']),
        ]


# =============================================================================
# WAREN-MODUL
# =============================================================================

class VerbleibOrt(models.Model):
    """
    Verbleib-Orte für Ausleihen (z.B. 'Im Labor', 'Mit nach Hause nehmen')
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    beschreibung = models.TextField(blank=True)
    
    # Reihenfolge für Anzeige
    reihenfolge = models.IntegerField(default=0)
    
    # Raumnummer erforderlich (z.B. für TH/Labor-Verbleib)
    raumnummer_erforderlich = models.BooleanField(default=False)
    
    # Status
    aktiv = models.BooleanField(default=True)
    
    # Audit
    erstellt_am = models.DateTimeField(auto_now_add=True)
    aktualisiert_am = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Verbleib Orte"
        ordering = ['reihenfolge', 'name']
        indexes = [
            models.Index(fields=['aktiv', 'reihenfolge']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['name'],
                condition=models.Q(aktiv=True),
                name='unique_verbleib_name_when_active'
            )
        ]

    def __str__(self):
        return self.name


class Warenkategorie(models.Model):
    """
    Kategorien für Waren (z.B. 'Werkzeuge', 'Elektronik', 'Laborgeräte')
    """
    ROLLEN_CHOICES = [
        ('Student', 'Student'),
        ('Mitarbeiter', 'Mitarbeiter'),
        ('Laborleiter', 'Laborleiter'),
        ('Admin', 'Admin'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    beschreibung = models.TextField(blank=True)
    
    # Minimale Rolle für Ausleihe (alle Rollen >= diese Rolle dürfen ausleihen)
    minimale_rolle = models.CharField(max_length=20, choices=ROLLEN_CHOICES, default='Student')
    
    # Für welches Labor (NULL = global verfügbar)
    labor_id = models.UUIDField(null=True, blank=True)
    
    # Status
    aktiv = models.BooleanField(default=True)
    
    # Audit
    erstellt_am = models.DateTimeField(auto_now_add=True)
    aktualisiert_am = models.DateTimeField(auto_now=True)
    
    # Gesperrte Verbleib-Orte für diese Kategorie
    # (diese Verbleib-Orte können nicht gewählt werden, wenn Ware dieser Kategorie im Warenkorb ist)
    gesperrte_verbleib_orte = models.ManyToManyField(
        VerbleibOrt,
        related_name='gesperrt_fuer_kategorien',
        blank=True
    )
    
    # Sync
    scope = models.CharField(max_length=20, default='local')
    origin_server_id = models.CharField(max_length=100, blank=True)
    sync_version = models.IntegerField(default=1)

    class Meta:
        verbose_name_plural = "Warenkategorien"
        indexes = [
            models.Index(fields=['aktiv', 'name']),
            models.Index(fields=['labor_id', 'aktiv']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['name'],
                condition=models.Q(aktiv=True),
                name='unique_name_when_active'
            )
        ]

    def __str__(self):
        return self.name
    
    def kann_ausgeliehen_werden_von_rolle(self, benutzer_rolle: str) -> bool:
        """Prüft ob eine Rolle diese Kategorie ausleihen darf"""
        ROLLEN_HIERARCHIE = {
            'Student': 1,
            'Mitarbeiter': 2,
            'Laborleiter': 3,
            'Admin': 4
        }
        benutzer_level = ROLLEN_HIERARCHIE.get(benutzer_rolle, 0)
        min_level = ROLLEN_HIERARCHIE.get(self.minimale_rolle, 1)
        return benutzer_level >= min_level


class KategorieVerbleibRegel(models.Model):
    """
    Berechtigungsregel für Kombination aus Kategorie und Verbleib-Ort.
    Definiert welche minimale Rolle benötigt wird, um eine Ware
    dieser Kategorie an diesem Verbleib-Ort auszuleihen.
    """
    ROLLEN_CHOICES = [
        ('Student', 'Student'),
        ('Mitarbeiter', 'Mitarbeiter'),
        ('Laborleiter', 'Laborleiter'),
        ('Admin', 'Admin'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kategorie = models.ForeignKey(Warenkategorie, on_delete=models.CASCADE, related_name='verbleib_regeln')
    verbleib_ort = models.ForeignKey(VerbleibOrt, on_delete=models.CASCADE, related_name='kategorie_regeln')
    
    # Minimale Rolle für diese Kombination
    minimale_rolle = models.CharField(max_length=20, choices=ROLLEN_CHOICES, default='Student')
    
    # Wenn True, ist diese Kombination komplett gesperrt
    gesperrt = models.BooleanField(default=False)
    
    # Maximale Ausleihdauer in Tagen (null = unbegrenzt)
    maximale_leihdauer_tage = models.PositiveIntegerField(
        null=True, 
        blank=True,
        verbose_name="Max. Leihdauer (Tage)",
        help_text="Maximale Ausleihdauer in Tagen. Leer lassen für unbegrenzt."
    )
    
    # Audit
    erstellt_am = models.DateTimeField(auto_now_add=True)
    aktualisiert_am = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = "Kategorie-Verbleib Regeln"
        # Eindeutige Kombination aus Kategorie und Verbleib
        constraints = [
            models.UniqueConstraint(fields=['kategorie', 'verbleib_ort'], name='unique_kategorie_verbleib')
        ]
        indexes = [
            models.Index(fields=['kategorie', 'verbleib_ort']),
        ]
    
    def __str__(self):
        status = "gesperrt" if self.gesperrt else f"min. {self.minimale_rolle}"
        return f"{self.kategorie.name} / {self.verbleib_ort.name}: {status}"
    
    def darf_ausleihen(self, benutzer_rolle: str) -> bool:
        """Prüft ob eine Rolle diese Kombination ausleihen darf"""
        if self.gesperrt:
            return False
        
        ROLLEN_HIERARCHIE = {
            'Student': 1,
            'Mitarbeiter': 2,
            'Laborleiter': 3,
            'Admin': 4
        }
        benutzer_level = ROLLEN_HIERARCHIE.get(benutzer_rolle, 0)
        min_level = ROLLEN_HIERARCHIE.get(self.minimale_rolle, 1)
        return benutzer_level >= min_level


class Ware(models.Model):
    """
    Die eigentlichen ausleihbaren Gegenstände.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    beschreibung = models.TextField(blank=True)
    
    # RFID-Verknüpfung (optional, aber empfohlen)
    rfid_tag = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    
    # Kategorisierung (Mehrere Kategorien möglich)
    kategorien = models.ManyToManyField(Warenkategorie, related_name='waren', blank=True)
    schranknummer = models.CharField(max_length=50, blank=True)
    
    # Ausleih-Status
    ist_ausgeliehen = models.BooleanField(default=False, help_text="Ist die Ware aktuell ausgeliehen?")
    ist_gesperrt = models.BooleanField(default=False, help_text="Wurde die Ware manuell gesperrt?")
    sperr_grund = models.TextField(blank=True, help_text="Grund für die Sperrung")
    
    # Labor-Zugehörigkeit (für Berechtigungen)
    labor_id = models.UUIDField(null=True, blank=True)
    
    # Optional: Bild/QR-Code
    bild_url = models.CharField(max_length=500, blank=True)
    qr_code = models.CharField(max_length=255, blank=True, unique=True, null=True)
    
    # Status
    aktiv = models.BooleanField(default=True)
    
    # Audit
    erstellt_am = models.DateTimeField(auto_now_add=True)
    aktualisiert_am = models.DateTimeField(auto_now=True)
    erstellt_von = models.ForeignKey(Benutzer, on_delete=models.SET_NULL,
                                     null=True, related_name='erstellte_waren')

    class Meta:
        verbose_name_plural = "Waren"
        indexes = [
            models.Index(fields=['rfid_tag', 'aktiv']),
            models.Index(fields=['ist_ausgeliehen', 'aktiv']),
            models.Index(fields=['labor_id', 'aktiv']),
            models.Index(fields=['qr_code', 'aktiv']),
        ]

    def __str__(self):
        kategorien_namen = [k.name for k in self.kategorien.all()[:3]]
        kategorie_str = ', '.join(kategorien_namen) if kategorien_namen else 'Keine Kategorie'
        if self.kategorien.count() > 3:
            kategorie_str += f' +{self.kategorien.count() - 3} weitere'
        return f"{self.name} ({kategorie_str})"
    
    def ist_verfuegbar(self):
        """Prüft ob die Ware aktuell verfügbar (ausleihbar) ist"""
        return self.aktiv and not self.ist_ausgeliehen and not self.ist_gesperrt
    
    def kann_ausgeliehen_werden_von(self, benutzer, verbleib_ort=None):
        """
        Prüft ob ein bestimmter Benutzer diese Ware ausleihen darf.
        Optional mit Verbleib-Ort für Kategorie-Verbleib-Matrix-Prüfung.
        """
        if not self.ist_verfuegbar():
            return False, "Ware ist nicht verfügbar"
        
        # Prüfe minimale Rolle für alle Kategorien der Ware
        kategorien = self.kategorien.filter(aktiv=True)
        
        for kategorie in kategorien:
            # Prüfe Kategorie-Verbleib-Matrix wenn Verbleib-Ort angegeben
            if verbleib_ort:
                try:
                    regel = KategorieVerbleibRegel.objects.get(
                        kategorie=kategorie,
                        verbleib_ort=verbleib_ort
                    )
                    if regel.gesperrt:
                        return False, f"'{kategorie.name}' darf nicht nach '{verbleib_ort.name}' ausgeliehen werden"
                    if not regel.darf_ausleihen(benutzer.rolle):
                        return False, f"Mindestens Rolle '{regel.minimale_rolle}' für '{kategorie.name}' nach '{verbleib_ort.name}' erforderlich"
                except KategorieVerbleibRegel.DoesNotExist:
                    # Keine spezifische Regel - Standard (Student darf)
                    pass
            else:
                # Prüfung OHNE Verbleib-Ort: Prüfe ob es überhaupt einen erlaubten Verbleib-Ort gibt
                erlaubte_orte = self.get_erlaubte_verbleib_orte(benutzer.rolle)
                if not erlaubte_orte:
                    return False, f"'{kategorie.name}' ist für Ihre Rolle nicht ausleihbar"
        
        return True, "OK"
    
    def get_erlaubte_verbleib_orte(self, benutzer_rolle: str):
        """
        Gibt alle Verbleib-Orte zurück, an die diese Ware für die gegebene Rolle ausgeliehen werden darf.
        """
        from .models import VerbleibOrt  # Import hier um Zirkel zu vermeiden
        
        alle_orte = VerbleibOrt.objects.filter(aktiv=True)
        kategorien = self.kategorien.filter(aktiv=True)
        
        if not kategorien.exists():
            # Keine Kategorie = alle Orte erlaubt
            return list(alle_orte)
        
        erlaubte_orte = []
        
        for ort in alle_orte:
            ort_erlaubt = True
            for kategorie in kategorien:
                try:
                    regel = KategorieVerbleibRegel.objects.get(
                        kategorie=kategorie,
                        verbleib_ort=ort
                    )
                    if regel.gesperrt or not regel.darf_ausleihen(benutzer_rolle):
                        ort_erlaubt = False
                        break
                except KategorieVerbleibRegel.DoesNotExist:
                    # Keine Regel = Student darf (Standard)
                    pass
            
            if ort_erlaubt:
                erlaubte_orte.append(ort)
        
        return erlaubte_orte
    
    def get_strengste_regel(self, verbleib_ort):
        """
        Gibt die strengste Regel für diese Ware bei einem Verbleib-Ort zurück.
        Wird verwendet für Warenkorb-Validierung (strengste Regel gewinnt).
        """
        kategorien = self.kategorien.filter(aktiv=True)
        
        ROLLEN_HIERARCHIE = {
            'Student': 1,
            'Mitarbeiter': 2,
            'Laborleiter': 3,
            'Admin': 4
        }
        
        max_level = 1  # Student ist Standard
        gesperrt = False
        grund = None
        
        for kategorie in kategorien:
            try:
                regel = KategorieVerbleibRegel.objects.get(
                    kategorie=kategorie,
                    verbleib_ort=verbleib_ort
                )
                if regel.gesperrt:
                    return {
                        'gesperrt': True,
                        'minimale_rolle': None,
                        'grund': f"'{kategorie.name}' darf nicht nach '{verbleib_ort.name}' ausgeliehen werden"
                    }
                regel_level = ROLLEN_HIERARCHIE.get(regel.minimale_rolle, 1)
                if regel_level > max_level:
                    max_level = regel_level
                    grund = f"'{kategorie.name}' erfordert Rolle '{regel.minimale_rolle}' für '{verbleib_ort.name}'"
            except KategorieVerbleibRegel.DoesNotExist:
                continue
        
        # Rückwärts-Lookup für Rollenname
        rolle_name = [k for k, v in ROLLEN_HIERARCHIE.items() if v == max_level][0]
        
        return {
            'gesperrt': False,
            'minimale_rolle': rolle_name,
            'level': max_level,
            'grund': grund
        }


# =============================================================================
# AUSLEIH-MODUL (Kern)
# =============================================================================

class Ausleihe(models.Model):
    """
    Eine Ausleihe mit Status-Workflow.
    
    Workflow:
    1. aktiv → Ausleihe läuft
    2. rueckgabe_beantragt → User möchte zurückgeben
    3. zurueckgegeben → Physikalisch zurück, wartet auf Quittung
    4. abgeschlossen → Quittiert durch Mitarbeiter+
    """
    STATUS_CHOICES = [
        ('aktiv', 'Aktiv ausgeliehen'),
        ('rueckgabe_beantragt', 'Rückgabe beantragt'),
        ('zurueckgegeben', 'Zurückgegeben (wartet auf Quittung)'),
        ('abgeschlossen', 'Abgeschlossen'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Kernbeziehungen
    ware = models.ForeignKey(Ware, on_delete=models.PROTECT, related_name='ausleihen')
    benutzer = models.ForeignKey(Benutzer, on_delete=models.PROTECT, related_name='ausleihen')
    
    # Status-Workflow
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default='aktiv')
    
    # Zeitstempel
    ausgeliehen_am = models.DateTimeField(auto_now_add=True)
    geplante_rueckgabe = models.DateField(null=True, blank=True)
    
    # Rückgabe-Prozess
    rueckgabe_beantragt_am = models.DateTimeField(null=True, blank=True)
    tatsaechliche_rueckgabe = models.DateTimeField(null=True, blank=True)
    
    # Zusätzliche Infos
    notiz = models.TextField(blank=True, help_text="Notiz zur Ausleihe")
    verbleib_ort = models.CharField(max_length=255, blank=True, help_text="Wo wird die Ware genutzt?")
    
    # Status
    aktiv = models.BooleanField(default=True)
    
    # Audit
    erstellt_am = models.DateTimeField(auto_now_add=True)
    aktualisiert_am = models.DateTimeField(auto_now=True)
    
    # Sync
    scope = models.CharField(max_length=20, default='local')
    origin_server_id = models.CharField(max_length=100, blank=True)
    sync_version = models.IntegerField(default=1)

    class Meta:
        verbose_name_plural = "Ausleihen"
        constraints = [
            # Eine Ware kann nur einmal aktiv ausgeliehen sein
            models.UniqueConstraint(
                fields=['ware'],
                condition=models.Q(aktiv=True, status__in=['aktiv', 'rueckgabe_beantragt', 'zurueckgegeben']),
                name='eine_aktive_ausleihe_pro_ware'
            ),
        ]
        indexes = [
            models.Index(fields=['benutzer', 'status', 'aktiv']),
            models.Index(fields=['ware', 'status']),
            models.Index(fields=['status', 'aktiv']),
            models.Index(fields=['geplante_rueckgabe']),
            models.Index(fields=['ausgeliehen_am']),
        ]
        ordering = ['-ausgeliehen_am']

    def __str__(self):
        return f"{self.ware.name} an {self.benutzer} ({self.status})"
    
    def beantrage_rueckgabe(self):
        """User beantragt Rückgabe"""
        if self.status == 'aktiv':
            self.status = 'rueckgabe_beantragt'
            self.rueckgabe_beantragt_am = timezone.now()
            self.save()
            return True
        return False
    
    def markiere_zurueckgegeben(self):
        """Ware wurde physikalisch zurückgegeben"""
        if self.status in ['aktiv', 'rueckgabe_beantragt']:
            self.status = 'zurueckgegeben'
            self.tatsaechliche_rueckgabe = timezone.now()
            self.save()
            # Update Ware-Status
            self.ware.ist_ausgeliehen = False
            self.ware.save()
            return True
        return False
    
    def schliesse_ab(self, genehmigt_von, zustand='gut', kommentar=''):
        """Mitarbeiter+ quittiert die Rückgabe"""
        # Wenn Rückgabe beantragt oder aktiv, zuerst als zurückgegeben markieren
        if self.status in ['aktiv', 'rueckgabe_beantragt']:
            self.markiere_zurueckgegeben()
        
        if self.status == 'zurueckgegeben':
            self.status = 'abgeschlossen'
            self.save()
            
            # Erstelle Historie (mit dem Benutzer der quittiert)
            self._erstelle_historie(zustand, kommentar, genehmigt_von)
            return True
        return False
    
    def _erstelle_historie(self, zustand, kommentar, genehmigt_von=None):
        """Erstellt einen unveränderlichen Historieneintrag"""
        return AusleiheHistorie.objects.create(
            ausleihe_id=self.id,
            # Ware-Daten
            ware_id=self.ware.id,
            ware_name=self.ware.name,
            ware_beschreibung=self.ware.beschreibung,
            ware_rfid_tag=self.ware.rfid_tag or '',
            ware_kategorie=', '.join([k.name for k in self.ware.kategorien.all()]) if self.ware.kategorien.exists() else '',
            ware_schranknummer=self.ware.schranknummer,
            # Benutzer-Daten
            benutzer_id=self.benutzer.id,
            benutzer_vorname=self.benutzer.vorname,
            benutzer_nachname=self.benutzer.nachname,
            benutzer_email=self.benutzer.email,
            benutzer_rfid_karte=self.benutzer.rfid_karte or '',
            benutzer_rolle=self.benutzer.rolle,
            # Ausleih-Details
            ausgeliehen_am=self.ausgeliehen_am,
            geplante_rueckgabe=self.geplante_rueckgabe,
            tatsaechliche_rueckgabe=self.tatsaechliche_rueckgabe,
            verbleib_ort=self.verbleib_ort,
            ausleih_notiz=self.notiz,
            # Rückgabe-Details
            rueckgabe_beantragt_am=self.rueckgabe_beantragt_am,
            zustand=zustand,
            genehmigungs_kommentar=kommentar,
            # Wer hat quittiert
            genehmigt_von_id=genehmigt_von.id if genehmigt_von else None,
            genehmigt_von_name=f"{genehmigt_von.vorname} {genehmigt_von.nachname}" if genehmigt_von else '',
            genehmigt_von_rolle=genehmigt_von.rolle if genehmigt_von else ''
        )


class AusleiheHistorie(models.Model):
    """
    Unveränderliche Kopie für Langzeitarchivierung.
    Bleibt erhalten auch wenn Ware oder Benutzer gelöscht/deaktiviert werden.
    
    Dient als:
    - Audit-Trail
    - Statistiken
    - Nachweis auch nach Löschung der Originaldaten
    """
    ZUSTAND_CHOICES = [
        ('gut', 'Guter Zustand'),
        ('gebraucht', 'Gebrauchter Zustand'),
        ('beschaedigt', 'Beschädigt'),
        ('schwer_beschaedigt', 'Schwer beschädigt'),
        ('verloren', 'Verloren'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Referenz zur ursprünglichen Ausleihe (kann null sein wenn gelöscht)
    ausleihe_id = models.UUIDField(null=True, blank=True)
    
    # ========== WARE-DATEN (Kopie zum Zeitpunkt der Rückgabe) ==========
    ware_id = models.UUIDField()
    ware_name = models.CharField(max_length=255)
    ware_beschreibung = models.TextField(blank=True)
    ware_rfid_tag = models.CharField(max_length=255, blank=True)
    ware_kategorie = models.CharField(max_length=100, blank=True)
    ware_schranknummer = models.CharField(max_length=50, blank=True)
    
    # ========== BENUTZER-DATEN (Kopie) ==========
    benutzer_id = models.UUIDField()
    benutzer_vorname = models.CharField(max_length=100)
    benutzer_nachname = models.CharField(max_length=100)
    benutzer_email = models.EmailField(max_length=254)
    benutzer_rfid_karte = models.CharField(max_length=50, blank=True)
    benutzer_rolle = models.CharField(max_length=50)
    
    # ========== AUSLEIH-DETAILS ==========
    ausgeliehen_am = models.DateTimeField()
    geplante_rueckgabe = models.DateField(null=True, blank=True)
    tatsaechliche_rueckgabe = models.DateTimeField()
    verbleib_ort = models.CharField(max_length=255, blank=True)
    ausleih_notiz = models.TextField(blank=True)
    
    # ========== RÜCKGABE-DETAILS ==========
    rueckgabe_beantragt_am = models.DateTimeField(null=True, blank=True)
    
    # Zustand bei Rückgabe
    zustand = models.CharField(max_length=20, choices=ZUSTAND_CHOICES, default='gut')
    genehmigungs_kommentar = models.TextField(blank=True)
    
    # Wer hat genehmigt (Mitarbeiter+)
    genehmigt_von_id = models.UUIDField(null=True, blank=True)
    genehmigt_von_name = models.CharField(max_length=200, blank=True)
    genehmigt_von_rolle = models.CharField(max_length=50, blank=True)
    
    # Archivierung
    archiviert_am = models.DateTimeField(auto_now_add=True)
    
    # Sync
    scope = models.CharField(max_length=20, default='local')
    origin_server_id = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name_plural = "Ausleihe-Historie"
        indexes = [
            models.Index(fields=['ware_id']),
            models.Index(fields=['benutzer_id']),
            models.Index(fields=['ausgeliehen_am']),
            models.Index(fields=['tatsaechliche_rueckgabe']),
            models.Index(fields=['ware_kategorie']),
        ]
        ordering = ['-archiviert_am']


# =============================================================================
# LOGGING & MONITORING
# =============================================================================

class AusleiheLog(models.Model):
    """
    Detailliertes Event-Logging für das Ausleihsystem.
    Analog zu maschinenzugang/laborzugang im existierenden System.
    """
    AKTION_CHOICES = [
        ('ausleihe_erstellt', 'Ausleihe erstellt'),
        ('ausleihe_aktualisiert', 'Ausleihe aktualisiert'),
        ('rueckgabe_beantragt', 'Rückgabe beantragt'),
        ('ware_zurueckgegeben', 'Ware zurückgegeben'),
        ('rueckgabe_quittiert', 'Rückgabe quittiert'),
        ('ware_gesperrt', 'Ware gesperrt'),
        ('ware_entperrt', 'Ware entsperrt'),
        ('login', 'Benutzer eingeloggt'),
        ('logout', 'Benutzer ausgeloggt'),
        ('fehlversuch', 'Berechtigungsfehler'),
    ]
    
    METHODE_CHOICES = [
        ('rfid', 'RFID-Karte'),
        ('web', 'Web-Interface'),
        ('app', 'Mobile App'),
        ('api', 'API-Call'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Beteiligte Entitäten (optional, je nach Aktion)
    benutzer = models.ForeignKey(Benutzer, on_delete=models.SET_NULL, 
                                 null=True, blank=True, related_name='logs')
    benutzer_id_logged = models.UUIDField(null=True, blank=True)  # Falls Benutzer gelöscht
    
    ware = models.ForeignKey(Ware, on_delete=models.SET_NULL,
                            null=True, blank=True, related_name='logs')
    ware_id_logged = models.UUIDField(null=True, blank=True)
    
    ausleihe = models.ForeignKey(Ausleihe, on_delete=models.SET_NULL,
                                null=True, blank=True, related_name='logs')
    
    # Aktions-Details
    aktion = models.CharField(max_length=30, choices=AKTION_CHOICES)
    methode = models.CharField(max_length=10, choices=METHODE_CHOICES, default='web')
    
    # Zusätzliche Daten (JSON-fähig für flexible Erweiterung)
    details = models.JSONField(default=dict, blank=True)
    
    # RFID-Karte (falls per RFID)
    verwendete_rfid = models.CharField(max_length=50, blank=True)
    
    # IP und Gerät
    ip_address = models.CharField(max_length=45, blank=True)
    device_info = models.CharField(max_length=500, blank=True)
    
    # Zeitpunkt
    zeitpunkt = models.DateTimeField(auto_now_add=True)
    
    # Sync
    scope = models.CharField(max_length=20, default='local')
    origin_server_id = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name_plural = "Ausleihe-Logs"
        indexes = [
            models.Index(fields=['benutzer', 'zeitpunkt']),
            models.Index(fields=['ware', 'zeitpunkt']),
            models.Index(fields=['aktion', 'zeitpunkt']),
            models.Index(fields=['zeitpunkt']),
        ]
        ordering = ['-zeitpunkt']


# =============================================================================
# SYSTEM-KONFIGURATION
# =============================================================================

class AntennenEinstellung(models.Model):
    """
    Gespeicherte Antennen-Konfigurationen für verschiedene Labore/Stationen.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, help_text="z.B. 'Hauptlabor Station 1'")
    
    # Verknüpfung zum Labor
    labor_id = models.UUIDField(null=True, blank=True)
    
    # Serielle Verbindung
    port = models.CharField(max_length=50, default='/dev/ttyUSB0')
    baudrate = models.IntegerField(default=115200)
    
    # RFID-Parameter (die wichtigsten)
    rf_power = models.IntegerField(default=30, help_text="RF-Leistung in dBm (0-33)")
    work_mode = models.IntegerField(default=0, help_text="0=AnswerMode, 1=ActiveMode")
    
    # Geräte-Parameter als JSON (flexibel erweiterbar)
    geraete_params = models.JSONField(default=dict, blank=True, 
                                      help_text="Vollständige Geräteparameter")
    
    # Ist diese Konfiguration aktuell in Benutzung?
    ist_aktiv = models.BooleanField(default=False)
    
    # Status
    aktiv = models.BooleanField(default=True)
    
    # Audit
    erstellt_am = models.DateTimeField(auto_now_add=True)
    aktualisiert_am = models.DateTimeField(auto_now=True)
    erstellt_von = models.ForeignKey(Benutzer, on_delete=models.SET_NULL,
                                     null=True, related_name='erstellte_antennen_configs')

    class Meta:
        verbose_name_plural = "Antennen-Einstellungen"
        indexes = [
            models.Index(fields=['labor_id', 'ist_aktiv']),
            models.Index(fields=['aktiv']),
        ]



# =============================================================================
# SCHADENSMELDUNG-MODUL
# =============================================================================

class Schadensmeldung(models.Model):
    """
    Speichert Schadensmeldungen für Waren.
    
    Erstellt bei Rückgabe durch Student oder bei Inventur durch Mitarbeiter.
    Bei Rückgabe kann ein Mitarbeiter die Meldung quittieren.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Verknüpfungen
    ware = models.ForeignKey(
        Ware, 
        on_delete=models.CASCADE, 
        related_name='schadensmeldungen'
    )
    ausleihe = models.ForeignKey(
        Ausleihe, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name='schadensmeldungen',
        help_text="Verknüpfung zur Ausleihe (nur bei Rückgabe)"
    )
    
    # Schadensbeschreibung (Pflicht)
    beschreibung = models.TextField(
        help_text="Beschreibung des Schadens"
    )
    
    # Ersteller der Meldung
    # - Bei Rückgabe: Der Student (rückgeber)
    # - Bei Warenverwaltung: Der Mitarbeiter (wird als quittierer gespeichert)
    rueckgeber = models.ForeignKey(
        Benutzer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='erstellte_schadensmeldungen',
        help_text="Wer hat die Meldung erstellt (Student bei Rückgabe)"
    )
    erstellt_am = models.DateTimeField(auto_now_add=True)
    
    # Quittierung durch Mitarbeiter (nur bei Rückgabe relevant)
    quittiert = models.BooleanField(
        default=False,
        help_text="Wurde die Meldung vom Mitarbeiter quittiert?"
    )
    quittierer = models.ForeignKey(
        Benutzer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quittierte_schadensmeldungen',
        help_text="Mitarbeiter der quittiert hat"
    )
    quittiert_am = models.DateTimeField(
        null=True,
        blank=True
    )
    quittierer_beschreibung = models.TextField(
        blank=True,
        help_text="Ergänzende Beschreibung durch Quittierer"
    )
    
    class Meta:
        verbose_name_plural = "Schadensmeldungen"
        ordering = ['-erstellt_am']
        indexes = [
            models.Index(fields=['ware', 'quittiert']),
            models.Index(fields=['ausleihe']),
            models.Index(fields=['erstellt_am']),
        ]
    
    def __str__(self):
        status = "Quittiert" if self.quittiert else "Offen"
        return f"{self.ware.name} - {status} - {self.erstellt_am.strftime('%d.%m.%Y')}"
