"""
Ware Views für Waren-Endpunkte.
"""
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..services import WareService
from ..utils.decorators import jwt_required


@api_view(['GET', 'POST'])
@jwt_required
def waren_liste(request):
    """
    Alle Waren anzeigen oder neue Ware erstellen. Mit Pagination.
    """
    if request.method == 'GET':
        # Query Parameter
        kategorie_id = request.query_params.get('kategorie')
        verfuegbar = request.query_params.get('verfuegbar') == 'true'
        
        # Pagination
        try:
            limit = int(request.query_params.get('limit', 100))
            offset = int(request.query_params.get('offset', 0))
        except ValueError:
            limit = 100
            offset = 0
        
        result = WareService.get_waren_liste(
            user_id=request.user_id,
            kategorie_id=kategorie_id,
            verfuegbar_only=verfuegbar,
            offset=offset,
            limit=limit
        )
        
        return Response(result)
    
    elif request.method == 'POST':
        # Studenten dürfen keine Waren erstellen
        if request.user_role == 'Student':
            return Response({'error': 'Studenten dürfen keine Waren erstellen'}, status=403)
        
        data = request.data
        
        success, result = WareService.create_ware(
            request=request,
            name=data['name'],
            beschreibung=data.get('beschreibung', ''),
            rfid_tag=data.get('rfid_tag'),
            schranknummer=data.get('schranknummer', ''),
            labor_id=data.get('labor_id'),
            kategorie_ids=data.get('kategorie_ids', [])
        )
        
        if not success:
            return Response(result, status=403 if 'Nur Laborleiter' in result.get('error', '') else 400)
        
        return Response(result, status=201)


@api_view(['GET', 'PUT', 'DELETE'])
@jwt_required
def ware_detail(request, ware_id):
    """
    Einzelne Ware anzeigen, bearbeiten oder löschen.
    """
    if request.method == 'GET':
        ware = WareService.get_ware_detail(ware_id, request.user_id)
        
        if not ware:
            return Response({'error': 'Ware nicht gefunden'}, status=404)
        
        return Response(ware)
    
    elif request.method == 'PUT':
        data = request.data
        
        success, result = WareService.update_ware(
            request=request,
            ware_id=ware_id,
            **data
        )
        
        if not success:
            return Response(result, status=404 if 'nicht gefunden' in result.get('error', '') else 403)
        
        return Response(result)
    
    elif request.method == 'DELETE':
        success, result = WareService.delete_ware(request, ware_id)
        
        if not success:
            return Response(result, status=404)
        
        return Response(result)


@api_view(['GET'])
@jwt_required
def ware_schadensmeldungen(request, ware_id):
    """
    Schadensmeldungen für eine Ware anzeigen.
    """
    from ..models import Schadensmeldung
    
    try:
        schadensmeldungen = Schadensmeldung.objects.filter(
            ausleihe__ware_id=ware_id,
            quittiert=False
        ).select_related('ausleihe', 'ausleihe__benutzer')
        
        data = [{
            'id': str(s.id),
            'beschreibung': s.beschreibung,
            'gemeldet_am': s.gemeldet_am,
            'benutzer': f"{s.ausleihe.benutzer.vorname} {s.ausleihe.benutzer.nachname}",
        } for s in schadensmeldungen]
        
        return Response(data)
    except Exception as e:
        return Response({'error': str(e)}, status=400)
