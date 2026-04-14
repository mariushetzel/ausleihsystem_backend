"""
Ausleihe Views für Ausleihen-Endpunkte.
"""
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..services import AusleiheService
from ..utils.decorators import jwt_required


@api_view(['GET', 'POST'])
@jwt_required
def ausleihen_liste(request):
    """
    Ausleihen anzeigen oder neue Ausleihe erstellen.
    """
    if request.method == 'GET':
        status_filter = request.query_params.get('status')
        meine = request.query_params.get('meine') == 'true'
        
        data = AusleiheService.get_ausleihen_liste(
            user_id=request.user_id,
            user_role=request.user_role,
            status_filter=status_filter,
            meine_only=meine
        )
        
        return Response(data)
    
    elif request.method == 'POST':
        data = request.data
        
        success, result = AusleiheService.create_ausleihe(
            request=request,
            ware_id=data['ware_id'],
            geplante_rueckgabe=data.get('geplante_rueckgabe'),
            verbleib_ort_name=data.get('verbleib_ort', ''),
            notiz=data.get('notiz', '')
        )
        
        if not success:
            return Response(result, status=403 if 'Berechtigung' in result.get('error', '') else 400)
        
        return Response(result, status=201)


@api_view(['GET', 'PUT'])
@jwt_required
def ausleihe_detail(request, ausleihe_id):
    """
    Einzelne Ausleihe anzeigen oder aktualisieren.
    """
    if request.method == 'GET':
        from ..repositories import AusleiheRepository
        
        ausleihe = AusleiheRepository.get_by_id(ausleihe_id)
        if not ausleihe:
            return Response({'error': 'Ausleihe nicht gefunden'}, status=404)
        
        is_student = request.user_role == 'Student'
        anonymisiert = is_student and str(ausleihe.benutzer.id) != request.user_id
        benutzer_name = f"{ausleihe.benutzer.vorname} {ausleihe.benutzer.nachname}"
        
        return Response(AusleiheRepository.to_dict(ausleihe, benutzer_name, anonymisiert))
    
    elif request.method == 'PUT':
        data = request.data
        aktion = data.get('aktion')
        
        if aktion == 'rueckgabe_beantragen':
            success, result = AusleiheService.beantrage_rueckgabe(request, ausleihe_id)
        elif aktion == 'rueckgabe_quittieren':
            success, result = AusleiheService.quittiere_rueckgabe(
                request, 
                ausleihe_id,
                schadensmeldung=data.get('schadensmeldung')
            )
        elif aktion == 'ware_verschwunden':
            success, result = AusleiheService.markiere_als_verschwunden(request, ausleihe_id)
        else:
            return Response({'error': 'Ungültige Aktion'}, status=400)
        
        if not success:
            status_code = 403 if 'Berechtigung' in result.get('error', '') or 'Nur Laborleiter' in result.get('error', '') else 404
            return Response(result, status=status_code)
        
        return Response(result)
