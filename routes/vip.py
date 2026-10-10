@vip_bp.route("/api/v1/vip/smart-parlay", methods=["GET"])
@require_auth
@require_subscription
def generate_smart_parlay():
    if not db:
        return jsonify({"success": False, "error": "BD no disponible."}), 503
        
    try:
        hoy_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        docs = db.collection("partidos_verificados").where("fecha", "==", hoy_str).get()
        matches = [d.to_dict() for d in docs]
        
        if len(matches) < 4: # Fallback si hay pocos partidos hoy
            docs = db.collection("partidos_verificados").limit(15).get()
            matches = [d.to_dict() for d in docs]
            
        analyzed_picks = []
        for m in matches:
            a = analytics.generate_institutional_analysis(m)
            p_princ = a.get("pronostico_principal", {})
            if p_princ and p_princ.get("probabilidad"):
                prob_val = float(str(p_princ.get("probabilidad")).replace("%", ""))
                analyzed_picks.append({
                    "partido": f"{m.get('local')} vs {m.get('visita')}",
                    "seleccion": p_princ.get("seleccion"),
                    "probabilidad": f"{prob_val:.1f}%",
                    "prob_val": prob_val,
                    "cuota": p_princ.get("cuota_justa", "1.50")
                })
                    
        # Ordenar: Las más seguras primero
        analyzed_picks.sort(key=lambda x: x["prob_val"], reverse=True)
            
        def build_ticket(picks, name):
            cuota_total = 1.0
            for p in picks:
                c = str(p["cuota"]).replace(",", ".")
                cuota_total *= float(c) if c else 1.50
            return {
                "titulo": name,
                "cuota_total": f"{cuota_total:.2f}",
                "picks": [{"partido": p["partido"], "seleccion": p["seleccion"], "probabilidad": p["probabilidad"], "cuota": p["cuota"]} for p in picks]
            }
            
        tickets = {
            "duo_seguro": build_ticket(analyzed_picks[:2], "🔥 DÚO SEGURO (Alta Probabilidad)"),
            "triple_balanceado": build_ticket(analyzed_picks[:3], "⚡ TRIPLE BALANCEADO (+EV)"),
            "cuadruple_kamikaze": build_ticket(analyzed_picks[:4], "🚀 CUÁDRUPLE KAMIKAZE") if len(analyzed_picks) >= 4 else None
        }
        return jsonify({"success": True, "parlays": tickets}), 200
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
