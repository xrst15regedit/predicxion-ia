@admin_bp.route("/api/v1/admin/telegram/broadcast-parlay", methods=["POST"])
@require_auth
def broadcast_telegram_parlay():
    # Solo el dueño puede usar esto
    if not getattr(g, "is_owner", False) and g.user_email not in OWNER_EMAILS:
        return jsonify({"error": "No autorizado para transmitir a Telegram."}), 403
        
    try:
        from services.telegram_service import telegram_service
        data = request.get_json()
        
        html_message = telegram_service.format_parlay_message(data)
        result = telegram_service.send_message(html_message)
        
        if result.get("success"):
            return jsonify({"success": True, "message": "¡Combinada enviada a la comunidad con éxito!"}), 200
        else:
            return jsonify({"success": False, "error": result.get("error")}), 502
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
