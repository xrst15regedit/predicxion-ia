import os
import requests
import logging

logger = logging.getLogger("PredicXionCore")

class TelegramService:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.channel_id = os.getenv("TELEGRAM_CHANNEL_ID", "")

    def is_configured(self):
        return bool(self.token and self.channel_id)

    def send_message(self, text, chat_id=None):
        target_chat = chat_id or self.channel_id
        if not self.token or not target_chat:
            return {"success": False, "error": "Faltan credenciales de Telegram en el .env."}
        
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": target_chat,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                return {"success": True}
            return {"success": False, "error": resp.text}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def format_parlay_message(self, parlay_data):
        """Genera el HTML hermoso para el mensaje de Telegram."""
        titulo = parlay_data.get("titulo", "🔥 COMBINADA VIP DEL DÍA 🔥")
        cuota_total = parlay_data.get("cuota_total", "0.00")
        
        html = f"<b>{titulo}</b>\n\n"
        html += "🤖 <i>Analizado matemáticamente por PredicXion IA</i>\n\n"
        
        for i, pick in enumerate(parlay_data.get("picks", []), 1):
            html += f"<b>{i}. {pick.get('partido')}</b>\n"
            html += f"Pronóstico: <b>{pick.get('seleccion')}</b>\n"
            html += f"Confianza IA: {pick.get('probabilidad')} | Cuota: {pick.get('cuota')}\n\n"
            
        html += f"📊 <b>CUOTA TOTAL: {cuota_total}</b>\n\n"
        html += "💰 ¡Apuesta con responsabilidad!"
        return html

telegram_service = TelegramService()
