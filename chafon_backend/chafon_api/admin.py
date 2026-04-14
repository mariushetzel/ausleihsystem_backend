from django.contrib import admin
from . import models


@admin.register(models.Benutzer)
class BenutzerAdmin(admin.ModelAdmin):
    list_display = ['vorname', 'nachname', 'email', 'rolle', 'aktiv', 'letzter_login']
    list_filter = ['rolle', 'aktiv']
    search_fields = ['vorname', 'nachname', 'email', 'rfid_karte']
    readonly_fields = ['id', 'erstellt_am', 'aktualisiert_am', 'letzter_login']


@admin.register(models.Ware)
class WareAdmin(admin.ModelAdmin):
    list_display = ['name', 'get_kategorien', 'ist_ausgeliehen', 'schranknummer', 'aktiv']
    list_filter = ['kategorien', 'ist_ausgeliehen', 'aktiv']
    search_fields = ['name', 'rfid_tag', 'schranknummer']
    readonly_fields = ['id', 'erstellt_am', 'aktualisiert_am']
    filter_horizontal = ['kategorien']
    
    def get_kategorien(self, obj):
        return ', '.join([k.name for k in obj.kategorien.all()])
    get_kategorien.short_description = 'Kategorien'


@admin.register(models.Warenkategorie)
class WarenkategorieAdmin(admin.ModelAdmin):
    list_display = ['name', 'minimale_rolle', 'aktiv']
    list_filter = ['minimale_rolle', 'aktiv']
    search_fields = ['name']
    filter_horizontal = ['gesperrte_verbleib_orte']


@admin.register(models.VerbleibOrt)
class VerbleibOrtAdmin(admin.ModelAdmin):
    list_display = ['name', 'reihenfolge', 'aktiv']
    list_filter = ['aktiv']
    search_fields = ['name']
    ordering = ['reihenfolge', 'name']


@admin.register(models.ErlaubteEmailDomain)
class ErlaubteEmailDomainAdmin(admin.ModelAdmin):
    list_display = ['domain', 'beschreibung', 'aktiv']
    list_filter = ['aktiv']
    search_fields = ['domain', 'beschreibung']
    ordering = ['domain']


@admin.register(models.Ausleihe)
class AusleiheAdmin(admin.ModelAdmin):
    list_display = ['ware', 'benutzer', 'status', 'ausgeliehen_am', 'geplante_rueckgabe']
    list_filter = ['status', 'aktiv']
    search_fields = ['ware__name', 'benutzer__vorname', 'benutzer__nachname', 'benutzer__email']
    readonly_fields = ['id', 'erstellt_am', 'aktualisiert_am']
    date_hierarchy = 'ausgeliehen_am'


@admin.register(models.AusleiheHistorie)
class AusleiheHistorieAdmin(admin.ModelAdmin):
    list_display = ['ware_name', 'benutzer_name', 'tatsaechliche_rueckgabe', 'zustand']
    list_filter = ['zustand']
    search_fields = ['ware_name', 'benutzer_nachname', 'benutzer_email']
    readonly_fields = ['id', 'archiviert_am']  # Historie ist unveränderlich
    date_hierarchy = 'tatsaechliche_rueckgabe'
    
    def benutzer_name(self, obj):
        return f"{obj.benutzer_vorname} {obj.benutzer_nachname}"
    benutzer_name.short_description = 'Benutzer'


@admin.register(models.AusleiheLog)
class AusleiheLogAdmin(admin.ModelAdmin):
    list_display = ['zeitpunkt', 'aktion', 'benutzer', 'methode']
    list_filter = ['aktion', 'methode']
    search_fields = ['details']
    readonly_fields = ['id', 'zeitpunkt']
    date_hierarchy = 'zeitpunkt'


# Token und Einstellungen registrieren
admin.site.register(models.TokenPair)
admin.site.register(models.BenutzerKommentar)
admin.site.register(models.BenutzerWarenkategorieBerechtigung)
admin.site.register(models.SystemEinstellung)
admin.site.register(models.AntennenEinstellung)
admin.site.register(models.KategorieVerbleibRegel)
