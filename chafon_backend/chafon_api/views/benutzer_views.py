"""
Benutzer Views für Benutzerverwaltung.
"""
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..services import BenutzerService
from ..utils.decorators import jwt_required


@api_view(['GET', 'POST'])
@jwt_required
def benutzer_liste(request):
    """
    Liste aller Benutzer oder neuen Benutzer erstellen.
    """
    if request.method == 'GET':
        data = BenutzerService.get_benutzer_liste(request.user_role)
        return Response(data)
    
    elif request.method == 'POST':
        data = request.data
        
        success, result = BenutzerService.create_benutzer(
            request=request,
            email=data['email'],
            vorname=data['vorname'],
            nachname=data['nachname'],
            rolle=data.get('rolle', 'Student'),
            passwort=data.get('passwort'),
            rfid_karte=data.get('rfid_karte'),
            labor_id=data.get('labor_id')
        )
        
        if not success:
            return Response(result, status=403 if 'Berechtigung' in result.get('error', '') else 400)
        
        return Response(result, status=201)


@api_view(['GET', 'PUT', 'DELETE'])
@jwt_required
def benutzer_detail(request, benutzer_id):
    """
    Einzelnen Benutzer anzeigen, bearbeiten oder deaktivieren.
    """
    if request.method == 'GET':
        from ..repositories import BenutzerRepository
        benutzer = BenutzerRepository.get_by_id(benutzer_id)
        
        if not benutzer:
            return Response({'error': 'Benutzer nicht gefunden'}, status=404)
        
        return Response(BenutzerRepository.to_dict(benutzer))
    
    elif request.method == 'PUT':
        data = request.data
        
        success, result = BenutzerService.update_benutzer(
            request=request,
            benutzer_id=benutzer_id,
            **data
        )
        
        if not success:
            status_code = 403 if 'Berechtigung' in result.get('error', '') else 404
            return Response(result, status=status_code)
        
        return Response(result)
    
    elif request.method == 'DELETE':
        success, result = BenutzerService.delete_benutzer(request, benutzer_id)
        
        if not success:
            status_code = 403 if 'Berechtigung' in result.get('error', '') else 404
            return Response(result, status=status_code)
        
        return Response(result)


@api_view(['GET'])
@jwt_required
def check_card(request, rfid_karte):
    """
    Prüft ob eine RFID-Karte bereits vergeben ist.
    """
    vergeben, benutzer_info = BenutzerService.check_rfid_karte(
        rfid_karte,
        exclude_benutzer_id=request.query_params.get('exclude')
    )
    
    return Response({
        'vergeben': vergeben,
        'benutzer': benutzer_info
    })
