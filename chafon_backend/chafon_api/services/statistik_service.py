"""
Statistik Service für Ausleihsystem.
Berechnet Statistiken aus der AusleiheHistorie.
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from django.db.models import Count, F, Q, Avg, Max
from django.utils import timezone
from ..models import AusleiheHistorie, Ausleihe


class StatistikService:
    """Service für Statistik-Berechnungen."""

    @staticmethod
    def get_statistiken(von: Optional[datetime] = None, bis: Optional[datetime] = None) -> Dict:
        """
        Holt alle Statistiken für einen Zeitraum.
        Wenn kein Zeitraum angegeben, wird das aktuelle Kalenderjahr verwendet.
        """
        if von is None:
            now = timezone.now()
            von = datetime(now.year, 1, 1, tzinfo=timezone.get_current_timezone())
        if bis is None:
            bis = timezone.now()

        # Base QuerySet für Historie im Zeitraum
        historie_qs = AusleiheHistorie.objects.filter(
            ausgeliehen_am__date__gte=von.date(),
            ausgeliehen_am__date__lte=bis.date()
        )

        # 1. Gesamt-Ausleihen
        gesamt_ausleihen = historie_qs.count()

        # 2. Aktuell ausgeliehen
        aktuell_ausgeliehen = Ausleihe.objects.filter(
            status__in=['aktiv', 'rueckgabe_beantragt']
        ).count()

        # 3. Top 10 Ausleiher
        top_ausleiher = list(
            historie_qs.values(
                'benutzer_email',
                'benutzer_vorname',
                'benutzer_nachname'
            )
            .annotate(anzahl=Count('id'))
            .order_by('-anzahl')[:10]
        )

        # 4. Top 10 Waren
        top_waren = list(
            historie_qs.values(
                'ware_name',
                'ware_kategorie'
            )
            .annotate(anzahl=Count('id'))
            .order_by('-anzahl')[:10]
        )

        # 5. Top 10 Kategorien
        top_kategorien = list(
            historie_qs.exclude(ware_kategorie='')
            .values('ware_kategorie')
            .annotate(anzahl=Count('id'))
            .order_by('-anzahl')[:10]
        )

        # 6. Zustands-Verteilung
        zustand_qs = historie_qs.values('zustand').annotate(anzahl=Count('id'))
        zustand_verteilung = {item['zustand']: item['anzahl'] for item in zustand_qs}

        # 7. Top 10 Beschädiger
        beschaedigt_qs = historie_qs.filter(
            zustand__in=['beschaedigt', 'schwer_beschaedigt', 'verloren']
        )
        top_beschaediger = list(
            beschaedigt_qs.values(
                'benutzer_email',
                'benutzer_vorname',
                'benutzer_nachname'
            )
            .annotate(anzahl_beschaedigt=Count('id'))
            .order_by('-anzahl_beschaedigt')[:10]
        )

        # 8. Top 10 Verspätungen
        verspaetet_qs = historie_qs.filter(
            tatsaechliche_rueckgabe__isnull=False,
            geplante_rueckgabe__isnull=False,
            tatsaechliche_rueckgabe__gt=F('geplante_rueckgabe')
        )
        top_verspaetungen = list(
            verspaetet_qs.values(
                'benutzer_email',
                'benutzer_vorname',
                'benutzer_nachname'
            )
            .annotate(
                anzahl_verspaetet=Count('id'),
                max_verspaetung_tage=Max(
                    F('tatsaechliche_rueckgabe') - F('geplante_rueckgabe')
                )
            )
            .order_by('-anzahl_verspaetet')[:10]
        )
        # Konvertiere timedelta zu Tagen
        for item in top_verspaetungen:
            if item['max_verspaetung_tage']:
                item['max_verspaetung_tage'] = item['max_verspaetung_tage'].days
            else:
                item['max_verspaetung_tage'] = 0

        # Durchschnittliche Verspätung
        avg_verspaetung = 0
        if verspaetet_qs.exists():
            avg_result = verspaetet_qs.aggregate(
                avg=Avg(F('tatsaechliche_rueckgabe') - F('geplante_rueckgabe'))
            )
            if avg_result['avg']:
                avg_verspaetung = round(avg_result['avg'].days, 1)

        return {
            'zeitraum': {
                'von': von.date().isoformat(),
                'bis': bis.date().isoformat(),
            },
            'gesamt_ausleihen': gesamt_ausleihen,
            'aktuell_ausgeliehen': aktuell_ausgeliehen,
            'top_ausleiher': [
                {
                    'benutzer_name': f"{a['benutzer_vorname']} {a['benutzer_nachname']}",
                    'benutzer_email': a['benutzer_email'],
                    'anzahl': a['anzahl']
                }
                for a in top_ausleiher
            ],
            'top_waren': [
                {
                    'ware_name': w['ware_name'],
                    'ware_kategorie': w['ware_kategorie'],
                    'anzahl': w['anzahl']
                }
                for w in top_waren
            ],
            'top_kategorien': [
                {
                    'kategorie': k['ware_kategorie'],
                    'anzahl': k['anzahl']
                }
                for k in top_kategorien
            ],
            'zustand_verteilung': zustand_verteilung,
            'top_beschaediger': [
                {
                    'benutzer_name': f"{b['benutzer_vorname']} {b['benutzer_nachname']}",
                    'anzahl_beschaedigt': b['anzahl_beschaedigt']
                }
                for b in top_beschaediger
            ],
            'top_verspaetungen': [
                {
                    'benutzer_name': f"{v['benutzer_vorname']} {v['benutzer_nachname']}",
                    'anzahl_verspaetet': v['anzahl_verspaetet'],
                    'max_verspaetung_tage': v['max_verspaetung_tage']
                }
                for v in top_verspaetungen
            ],
            'durchschnittliche_verspaetung_tage': avg_verspaetung,
        }
