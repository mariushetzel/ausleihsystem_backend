"""
Views für API-Endpunkte.
"""
from .auth_views import register, login, logout, refresh_token, me
from .benutzer_views import benutzer_liste, benutzer_detail, check_card
from .ware_views import waren_liste, ware_detail, ware_schadensmeldungen
from .ausleihe_views import ausleihen_liste, ausleihe_detail
from .statistik_views import statistiken_liste

__all__ = [
    # Auth
    'register', 'login', 'logout', 'refresh_token', 'me',
    # Benutzer
    'benutzer_liste', 'benutzer_detail', 'check_card',
    # Waren
    'waren_liste', 'ware_detail', 'ware_schadensmeldungen',
    # Ausleihen
    'ausleihen_liste', 'ausleihe_detail',
    # Statistiken
    'statistiken_liste',
]
