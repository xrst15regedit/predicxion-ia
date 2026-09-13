from flask import Blueprint
from services.match_service import MatchService
from core.responses import success_response, error_response

matches_bp = Blueprint('matches_bp', __name__)
match_service = MatchService()

@matches_bp.route('/api/v1/matches/today', methods=['GET'])
def get_today_matches():
    try:
        data = match_service.get_todays_matches()
        return success_response(data=data, message="Partidos obtenidos correctamente")
    except Exception as e:
        return error_response(message="Error al obtener partidos", details=str(e), status=500)
