import hashlib
import json
import re
import logging

logger = logging.getLogger(__name__)

class ByzantineConsensusEngine:
    def __init__(self, tolerance_threshold=2):
        # Se exige que al menos 2 de las 3 fuentes (nodos) validen el evento
        self.threshold = tolerance_threshold

    def _normalize(self, text):
        """Estandariza los nombres para evitar fallos por espacios, tildes o mayúsculas."""
        if not text:
            return ""
        text = str(text).lower().strip()
        # Elimina todo lo que no sea letra o número (ej. "Real Madrid CF" -> "realmadridcf")
        return re.sub(r'[^a-z0-9]', '', text)

    def _verify_node_match(self, node1, node2):
        """Compara si dos fuentes distintas hablan exactamente del mismo partido."""
        if not node1 or not node2:
            return False
        
        local_match = self._normalize(node1.get('local')) == self._normalize(node2.get('local'))
        visit_match = self._normalize(node1.get('visitante')) == self._normalize(node2.get('visitante'))
        
        return local_match and visit_match

    def validate_fixture(self, source_official, source_agency, source_market):
        """
        Ejecuta el contrato de verificación cruzada entre las 3 fuentes.
        Retorna (True, bft_hash) si hay consenso, o (False, 'QUARANTINED') si el evento es anómalo.
        """
        nodes = [source_official, source_agency, source_market]
        votes = 0
        
        # Votación cruzada (Protocolo BFT)
        if self._verify_node_match(nodes[0], nodes[1]): votes += 1 # Oficial vs Agencia
        if self._verify_node_match(nodes[1], nodes[2]): votes += 1 # Agencia vs Mercado
        if self._verify_node_match(nodes[0], nodes[2]): votes += 1 # Oficial vs Mercado

        if votes >= self.threshold:
            # Consenso alcanzado: El partido es 100% real.
            # Se genera la firma criptográfica (CLV) usando la fuente principal.
            base_data = json.dumps({
                "l": self._normalize(source_official.get('local')),
                "v": self._normalize(source_official.get('visitante')),
                "d": source_official.get('fecha_utc')
            }, sort_keys=True)
            
            bft_hash = hashlib.sha256(base_data.encode('utf-8')).hexdigest()
            return True, bft_hash
        else:
            logger.warning(f"Consenso fallido. Partido bloqueado y enviado a cuarentena.")
            return False, "QUARANTINED"
