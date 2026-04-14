"""
Middleware für das Chafon API.
"""


class DisableCSRFForAPI:
    """
    Deaktiviert CSRF für API-Endpunkte, da wir JWT-Authentifizierung verwenden.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # CSRF für alle /api/ URLs deaktivieren
        if request.path.startswith('/api/'):
            setattr(request, '_dont_enforce_csrf_checks', True)
        
        response = self.get_response(request)
        return response
