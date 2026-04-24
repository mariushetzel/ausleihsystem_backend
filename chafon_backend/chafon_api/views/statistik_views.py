"""
Statistik Views für Ausleihsystem.
"""
from datetime import datetime
from rest_framework.decorators import api_view
from rest_framework.response import Response
from ..services.statistik_service import StatistikService
from ..utils.decorators import jwt_required, require_role


@api_view(['GET'])
@jwt_required
@require_role(['Mitarbeiter', 'Laborleiter', 'Admin'])
def statistiken_liste(request):
    """
    Statistiken für einen Zeitraum abrufen.
    Query-Parameter:
    - von: ISO-Datum (optional, Default: 1.1. aktuelles Jahr)
    - bis: ISO-Datum (optional, Default: heute)
    """
    von_str = request.query_params.get('von')
    bis_str = request.query_params.get('bis')

    von = None
    bis = None

    if von_str:
        try:
            von = datetime.strptime(von_str, '%Y-%m-%d')
        except ValueError:
            return Response({'error': 'Ungültiges Datum für "von". Format: YYYY-MM-DD'}, status=400)

    if bis_str:
        try:
            bis = datetime.strptime(bis_str, '%Y-%m-%d')
            # Bis zum Ende des Tages
            from datetime import time
            bis = datetime.combine(bis.date(), time(23, 59, 59))
        except ValueError:
            return Response({'error': 'Ungültiges Datum für "bis". Format: YYYY-MM-DD'}, status=400)

    data = StatistikService.get_statistiken(von=von, bis=bis)
    return Response(data)
