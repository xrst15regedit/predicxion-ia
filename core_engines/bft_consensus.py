# ======================================================================================
# ARCHIVO: core_engines/predictive_engine.py
# DESCRIPCIÓN: Motor Estadístico y Cuantitativo de Fútbol
# MODELOS: Distribución de Poisson Bivariada, Matriz de Marcador Exacto y Criterio de Kelly
# ======================================================================================

import math
import numpy as np

class PredictiveSportsEngine:
    @staticmethod
    def _poisson_probability(k: int, lamb: float) -> float:
        """Calcula la probabilidad puntual de Poisson P(X = k; lambda)."""
        if lamb <= 0:
            return 1.0 if k == 0 else 0.0
        return (math.pow(lamb, k) * math.exp(-lamb)) / math.factorial(k)

    @classmethod
    def calculate_match_matrix(cls, lambda_home: float, lambda_away: float, max_goals: int = 6) -> dict:
        """
        Genera la matriz de probabilidades de goles y calcula los mercados principales:
        1X2, Over/Under 1.5, 2.5, 3.5, Ambos Marcan (BTTS) y Marcadores Exactos.
        """
        lh = max(0.2, float(lambda_home))
        la = max(0.2, float(lambda_away))

        matrix = np.zeros((max_goals + 1, max_goals + 1))
        for i in range(max_goals + 1):
            p_i = cls._poisson_probability(i, lh)
            for j in range(max_goals + 1):
                matrix[i, j] = p_i * cls._poisson_probability(j, la)

        total = float(matrix.sum())
        if total > 0:
            matrix /= total

        # Probabilidades 1X2
        prob_home = float(np.sum(np.tril(matrix, -1)))
        prob_draw = float(np.sum(np.diag(matrix)))
        prob_away = float(np.sum(np.triu(matrix, 1)))

        # Mercados de Total de Goles
        prob_under_1_5 = float(sum(matrix[i, j] for i in range(max_goals + 1) for j in range(max_goals + 1) if i + j <= 1))
        prob_under_2_5 = float(sum(matrix[i, j] for i in range(max_goals + 1) for j in range(max_goals + 1) if i + j <= 2))
        prob_under_3_5 = float(sum(matrix[i, j] for i in range(max_goals + 1) for j in range(max_goals + 1) if i + j <= 3))

        # Ambos Equipos Anotan (BTTS)
        prob_btts = float(np.sum(matrix[1:, 1:]))

        # Top 3 Marcadores Exactos más probables
        exact_scores = []
        for i in range(max_goals + 1):
            for j in range(max_goals + 1):
                exact_scores.append((f"{i}-{j}", round(float(matrix[i, j]) * 100, 1)))
        exact_scores.sort(key=lambda x: x, reverse=True)

        return {
            "1X2": {
                "1": round(prob_home * 100, 1),
                "X": round(prob_draw * 100, 1),
                "2": round(prob_away * 100, 1)
            },
            "goles": {
                "over_1_5": round((1.0 - prob_under_1_5) * 100, 1),
                "under_1_5": round(prob_under_1_5 * 100, 1),
                "over_2_5": round((1.0 - prob_under_2_5) * 100, 1),
                "under_2_5": round(prob_under_2_5 * 100, 1),
                "over_3_5": round((1.0 - prob_under_3_5) * 100, 1),
                "under_3_5": round(prob_under_3_5 * 100, 1)
            },
            "btts": {
                "yes": round(prob_btts * 100, 1),
                "no": round((1.0 - prob_btts) * 100, 1)
            },
            "cuotas_justas": {
                "1": round(1.0 / prob_home, 2) if prob_home > 0 else None,
                "X": round(1.0 / prob_draw, 2) if prob_draw > 0 else None,
                "2": round(1.0 / prob_away, 2) if prob_away > 0 else None
            },
            "marcadores_probables": exact_scores[:3]
        }

    @staticmethod
    def calculate_value_and_kelly(prob_percent: float, market_odds: float, bankroll: float = 1000.0) -> dict:
        """Calcula el Valor Esperado (EV) y el dimensionamiento de apuesta con Kelly Fraccional (0.25)."""
        if market_odds <= 1.0 or prob_percent <= 0:
            return {"ev_percent": 0.0, "value_detected": False, "stake_percent": 0.0, "monto_sugerido": 0.0}

        p = prob_percent / 100.0
        implied_p = 1.0 / market_odds
        edge = p - implied_p
        ev = (p * market_odds) - 1.0

        b = market_odds - 1.0
        q = 1.0 - p
        full_kelly = (b * p - q) / b if b > 0 else 0.0
        fractional_kelly = max(0.0, full_kelly * 0.25)

        has_value = ev > 0 and edge >= 0.02
        stake_pct = min(2.5, round(fractional_kelly * 100, 2)) if has_value else 0.0

        return {
            "ev_percent": round(ev * 100, 2),
            "edge_percent": round(edge * 100, 2),
            "value_detected": has_value,
            "stake_percent": stake_pct,
            "monto_sugerido": round(bankroll * (stake_pct / 100.0), 2)
        }
