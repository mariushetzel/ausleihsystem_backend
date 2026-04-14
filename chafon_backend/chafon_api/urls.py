"""
URL-Konfiguration für das Ausleihsystem API.

ACHTUNG: Migration zu neuen Views läuft.
- Neue Views: auth_views, benutzer_views, ware_views, ausleihe_views
- Alte Views: views (für nicht migrierte Endpunkte)
"""
from django.urls import path

# Neue refactorte Views
from .views import (
    auth_views,
    benutzer_views,
    ware_views,
    ausleihe_views,
)

# Alte Views (für nicht migrierte Endpunkte)
from . import views_legacy as old_views

urlpatterns = [
    # =============================================================================
    # AUTHENTIFIZIERUNG (neue Views)
    # =============================================================================
    path('login/', auth_views.login, name='login'),
    path('register/', auth_views.register, name='register'),
    path('logout/', auth_views.logout, name='logout'),
    path('refresh/', auth_views.refresh_token, name='refresh_token'),
    path('me/', auth_views.me, name='me'),
    
    # =============================================================================
    # BENUTZER (neue Views)
    # =============================================================================
    path('benutzer/', benutzer_views.benutzer_liste, name='benutzer_liste'),
    path('benutzer/<uuid:benutzer_id>/', benutzer_views.benutzer_detail, name='benutzer_detail'),
    path('check-card/<str:rfid_karte>/', benutzer_views.check_card, name='check_card'),
    
    # =============================================================================
    # WAREN (neue Views)
    # =============================================================================
    path('waren/', ware_views.waren_liste, name='waren_liste'),
    path('waren/<uuid:ware_id>/', ware_views.ware_detail, name='ware_detail'),
    path('waren/<uuid:ware_id>/schadensmeldungen/', ware_views.ware_schadensmeldungen, name='ware_schadensmeldungen'),
    
    # =============================================================================
    # AUSLEIHEN (neue Views)
    # =============================================================================
    path('ausleihen/', ausleihe_views.ausleihen_liste, name='ausleihen_liste'),
    path('ausleihen/<uuid:ausleihe_id>/', ausleihe_views.ausleihe_detail, name='ausleihe_detail'),
    
    # =============================================================================
    # KATEGORIEN (alte Views - noch nicht migriert)
    # =============================================================================
    path('kategorien/', old_views.kategorien_liste, name='kategorien_liste'),
    path('kategorien/<uuid:kategorie_id>/', old_views.kategorie_detail, name='kategorie_detail'),
    path('kategorien/<uuid:kategorie_id>/verbleib/', old_views.kategorie_verbleib_sperren, name='kategorie_verbleib_sperren'),
    
    # =============================================================================
    # KATEGORIE-VERBLEIB MATRIX (alte Views - noch nicht migriert)
    # =============================================================================
    path('kategorie-verbleib-matrix/', old_views.kategorie_verbleib_matrix, name='kategorie_verbleib_matrix'),
    path('kategorie-verbleib-regel/', old_views.kategorie_verbleib_regel, name='kategorie_verbleib_regel'),
    path('max-leihdauer/', old_views.max_leihdauer_abfragen, name='max_leihdauer'),
    path('verfuegbare-zeitraeume/', old_views.verfuegbare_zeitraeume, name='verfuegbare_zeitraeume'),
    
    # =============================================================================
    # VERBLEIB ORTE (alte Views - noch nicht migriert)
    # =============================================================================
    path('verbleib-orte/', old_views.verbleib_orte_liste, name='verbleib_orte_liste'),
    path('verbleib-orte/<uuid:ort_id>/', old_views.verbleib_ort_detail, name='verbleib_ort_detail'),
    
    # =============================================================================
    # E-MAIL DOMAINS (alte Views - noch nicht migriert)
    # =============================================================================
    path('email-domains/', old_views.email_domains_liste, name='email_domains_liste'),
    path('email-domains/<uuid:domain_id>/', old_views.email_domain_detail, name='email_domain_detail'),
    
    # =============================================================================
    # HISTORIE (alte Views - noch nicht migriert)
    # =============================================================================
    path('historie/', old_views.historie_liste, name='historie_liste'),
    
    # =============================================================================
    # RFID / HARDWARE (alte Views - noch nicht migriert)
    # =============================================================================
    path('getPorts/', old_views.get_ports, name='get_ports'),
    path('openDevice/', old_views.open_device, name='open_device'),
    path('closeDevice/', old_views.close_device, name='close_device'),
    path('scanningStatus/', old_views.get_scanning_status, name='scanning_status'),
    path('startCounting/', old_views.start_counting, name='start_counting'),
    path('getTagInfo/', old_views.get_tag_info, name='get_tag_info'),
    path('inventoryStop/', old_views.inventory_stop, name='inventory_stop'),
    path('getDevicePara/', old_views.get_device_para, name='get_device_para'),
    path('setDevicePara/', old_views.set_device_para, name='set_device_para'),
    path('rebootDevice/', old_views.reboot_device, name='reboot_device'),
    
    # =============================================================================
    # KARTENLESER (alte Views - noch nicht migriert)
    # =============================================================================
    path('startCardReader/', old_views.start_card_reader, name='start_card_reader'),
    path('getCardReaderData/', old_views.get_card_reader_data, name='get_card_reader_data'),
    path('stopCardReader/', old_views.stop_card_reader, name='stop_card_reader'),
    
    # =============================================================================
    # SCHADENSMELDUNGEN (alte Views - noch nicht migriert)
    # =============================================================================
    path('schadensmeldungen/', old_views.schadensmeldungen_liste, name='schadensmeldungen_liste'),
    path('schadensmeldungen/<uuid:meldung_id>/', old_views.schadensmeldung_detail, name='schadensmeldung_detail'),
    path('schadensmeldungen/offen/', old_views.offene_schadensmeldungen, name='offene_schadensmeldungen'),
    
    # =============================================================================
    # SYSTEM-EINSTELLUNGEN (alte Views - noch nicht migriert)
    # =============================================================================
    path('system-einstellungen/', old_views.system_einstellungen_liste, name='system_einstellungen_liste'),
    path('system-einstellungen/<str:schluessel>/', old_views.system_einstellung_detail, name='system_einstellung_detail'),
    path('system-einstellungen-aktualisieren/', old_views.system_einstellung_aktualisieren, name='system_einstellung_aktualisieren'),
    path('system-einstellungen-oeffentlich/', old_views.system_einstellungen_oeffentlich, name='system_einstellungen_oeffentlich'),
    
    # =============================================================================
    # HEALTH CHECKS (alte Views - noch nicht migriert)
    # =============================================================================
    path('ping/', old_views.ping, name='ping'),
    path('ping-auth/', old_views.ping_auth, name='ping_auth'),
]
