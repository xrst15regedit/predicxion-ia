from flask import jsonify

def success_response(data, message="Operación exitosa", status=200):
    return jsonify({
        "success": True,
        "message": message,
        "data": data
    }), status

def error_response(message="Ha ocurrido un error", status=400, details=None):
    response = {
        "success": False,
        "message": message
    }
    if details:
        response["details"] = details
    return jsonify(response), status
