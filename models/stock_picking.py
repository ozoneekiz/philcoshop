import logging
import json
import requests

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Timeout explícito para requests HTTP
REQUEST_TIMEOUT = 10
STATE_MAPPING = {
    'assigned': 'assigned',
    'done': 'shipped',
    'cancel': 'cancelled',
}
class StockPicking(models.Model):
    _name = 'stock.picking'
    _inherit = ['stock.picking', 'philco.api.mixin']

    def _map_odoo_state_to_laravel(self, odoo_state):
        """
        Mapea un estado de Odoo a su equivalente en Laravel.
        
        Args:
            odoo_state (str): Estado actual del pedido en Odoo
                             (draft, sent, sale, cancel, etc.)
        
        Returns:
            str: Estado mapeado para Laravel (pending, confirmed, cancelled, etc.)
        """
        laravel_state = STATE_MAPPING.get(odoo_state)
        
        if not laravel_state:
            _logger.warning(
                "Estado de Odoo '%s' no tiene mapeo definido. "
                "Se seguirá enviando la notificación pero con estado original.",
                odoo_state
            )
            # Si no está en el mapeo, enviar el estado original
            laravel_state = odoo_state
        
        return laravel_state
    
    def _build_order_payload(self, settings, old_state=None):
        """
        Construye el payload JSON a enviar a Laravel.
        
        Args:
            settings (philco.conexion): Configuración activa
            old_state (str, optional): Estado anterior del pedido (para logging)
        
        Returns:
            dict: Payload con estructura requerida
        """
        laravel_status = self._map_odoo_state_to_laravel(self.state)
        
        payload = {
            'status': laravel_status,
            'odoo_state': self.state,
            'odoo_order_id': self.sale_id.id,
            'odoo_stock_picking_id': self.id,
        }
        
        return payload
    def notify_philco_on_shipped(self):
        try:
            settings = self._get_philco_settings()
        except UserError as e:
            # No hay configuración activa. Log pero no bloqueamos el flujo.
            _logger.warning(
                "No se puede notificar estado del pedido %s (%s): %s",
                self.id, self.name, str(e)
            )
            return False

        try:
            # Construir URL final: {api_endpoint}/orders/{id}/status
            endpoint_url = settings.api_endpoint.rstrip('/')
            url = f'{endpoint_url}/orders/{self.sale_id.id}/status'
            
            # Construir headers y payload
            headers = self._build_philco_headers(settings)
            payload = self._build_order_payload(settings)
            
            _logger.info(
                "Enviando notificación de estado a Philco Shop. "
                "Pedido: %s (%s) | Estado: %s | URL: %s",
                self.id, self.name, self.state, url
            )
            
            # Ejecutar solicitud POST
            response = requests.put(
                url,
                headers=headers,
                json=payload,
                timeout=REQUEST_TIMEOUT
            )
            print(payload)
            # Validar respuesta exitosa (solo 200-201)
            if response.status_code in (200, 201):
                _logger.info(
                    "Notificación enviada exitosamente. "
                    "Pedido: %s (%s) | Status code: %d",
                    self.id, self.name, response.status_code
                )
                return True
            else:
                # Respuesta con código no esperado
                response_text = response.text[:200] if response.text else "(sin contenido)"
                _logger.warning(
                    "Respuesta inesperada de Philco Shop. "
                    "Pedido: %s (%s) | Status code: %d | Respuesta: %s",
                    self.id, self.name, response.status_code, response_text
                )
                return False

        except requests.exceptions.Timeout:
            _logger.warning(
                "Timeout al conectar con Philco Shop. "
                "Pedido: %s (%s) | Timeout: %d segundos",
                self.id, self.name, REQUEST_TIMEOUT
            )
            return False

        except requests.exceptions.ConnectionError as e:
            _logger.warning(
                "Error de conexión con Philco Shop. "
                "Pedido: %s (%s) | Detalles: %s",
                self.id, self.name, str(e)
            )
            return False

        except requests.exceptions.RequestException as e:
            _logger.warning(
                "Error en solicitud HTTP a Philco Shop. "
                "Pedido: %s (%s) | Detalles: %s",
                self.id, self.name, str(e)
            )
            return False

        except Exception as e:
            _logger.exception(
                "Error inesperado al notificar a Philco Shop. "
                "Pedido: %s (%s) | Detalles: %s",
                self.id, self.name, str(e)
            )
            return False
   
    # ejecutar el envio cuando se presiona el botoon button_validate
    def button_validate(self):
        res = super().button_validate()
        self.notify_philco_on_shipped()
        return res