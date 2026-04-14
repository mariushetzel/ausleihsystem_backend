"""
Repositories für Datenbankzugriffe.
"""
from .benutzer_repository import BenutzerRepository
from .ware_repository import WareRepository
from .ausleihe_repository import AusleiheRepository

__all__ = [
    'BenutzerRepository',
    'WareRepository',
    'AusleiheRepository',
]
