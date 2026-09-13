from firebase_admin import firestore

class MatchService:
    def __init__(self):
        self.db = firestore.client()

    def get_todays_matches(self):
        """Lógica separada del controlador web"""
        matches_ref = self.db.collection('partidos_verificados').limit(20)
        docs = matches_ref.stream()
        return [doc.to_dict() for doc in docs]
