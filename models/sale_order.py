import logging
import json
import requests

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Timeout explícito para requests HTTP
REQUEST_TIMEOUT = 10

# Estados de Odoo a Laravel
STATE_MAPPING = {
    'draft': 'pending',
    'sent': 'pending',
    'sale': 'confirmed',
    'cancel': 'cancelled',
}


class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['sale.order', 'philco.api.mixin']

    #agregar un numevo campo para guardar el nombre de la empresa trasnportista cueire o de carga
    transport_company_name = fields.Char(string="Empresa Transportista", help="Nombre de la empresa transportista o de carga asociada al pedido.")
    label_printed = fields.Boolean(string="Etiqueta Impresa", copy=False)
    package_count = fields.Integer(string="Nro. de paquetes", default=1)

    def _get_shipping_label_address(self):
        self.ensure_one()
        partner = self.partner_id
        address_parts = [
            partner.street,
            partner.city,
            partner.state_id.name if partner.state_id else False,
        ]
        return ", ".join(part for part in address_parts if part) or "Sin direccion registrada"

    def _get_shipping_label_document(self):
        self.ensure_one()
        partner = self.partner_id
        document_parts = [
            partner.l10n_latam_identification_type_id.name if partner.l10n_latam_identification_type_id else False,
            partner.vat,
        ]
        return " ".join(part for part in document_parts if part)

    def _get_valid_shipping_label_orders(self):
        valid_orders = self.env['sale.order']
        errors = []

        for order in self:
            missing_fields = []
            if not order.partner_id:
                missing_fields.append("cliente")
            if not order.transport_company_name:
                missing_fields.append("empresa transportista")
            if order.package_count < 1:
                missing_fields.append("nro. de paquetes mayor a 0")

            if missing_fields:
                errors.append("%s: falta %s" % (order.name, ", ".join(missing_fields)))
            else:
                valid_orders |= order

        return valid_orders, errors

    def _print_shipping_labels(self, report_xmlid):
        if not self:
            raise UserError("Selecciona al menos un pedido para imprimir etiquetas.")

        valid_orders, errors = self._get_valid_shipping_label_orders()
        if not valid_orders:
            raise UserError(
                "No hay pedidos validos para imprimir etiquetas:\n%s" % "\n".join(errors)
            )

        valid_orders.write({'label_printed': True})
        return self.env.ref(report_xmlid).report_action(valid_orders)

    def action_print_shipping_label_a6(self):
        return self._print_shipping_labels('philcoshop.action_shipping_label_a6_report')

    def action_print_shipping_label_a4(self):
        return self._print_shipping_labels('philcoshop.action_shipping_label_a4_report')


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
            'odoo_order_id': self.id,
            'odoo_order_name': self.name,
        }
        
        return payload

    def _notify_philco_order_status(self, force=False):
        """
        Notifica a Laravel sobre el cambio de estado del pedido.
        
        Este método:
        - Obtiene la configuración activa de philco.conexion
        - Construye la URL final del endpoint
        - Arma el payload JSON
        - Ejecuta la solicitud POST
        - Loguea el resultado y maneja errores en modo tolerante
        
        Args:
            force (bool): Si True, envía la notificación incluso si hay dudas.
                         Útil para forzar sincronización manual.
        
        Returns:
            bool: True si la notificación fue exitosa, False en caso contrario.
        """
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
            url = f'{endpoint_url}/orders/{self.id}/status'
            
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
            print(response.status_code)
            print(response.text)
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

    def _get_order_signature_base64(self):
        """Devuelve la firma del pedido en base64 (sin prefijo data URI)."""
        self.ensure_one()

        signature_value = self.signature
        if not signature_value:
            return False

        if isinstance(signature_value, bytes):
            return signature_value.decode('utf-8')

        return signature_value

    # funcion para enviar campo siganure a laravel
    def _notify_philco_order_signature(self, signature=None):
        """
        envia a laravel la imagen que contiene el campo signture
        en base 64
        
        Args:
            signature (str, optional): Firma en base64. Si no se envía,
                                      usa self.signature.

        Returns:
            bool: True si la notificación fue exitosa, False en caso contrario.
        """
        try:
            settings = self._get_philco_settings()
        except UserError as e:
            _logger.warning(
                "No se puede notificar firma del pedido %s (%s): %s",
                self.id, self.name, str(e)
            )
            return False

        self.ensure_one()

        signature_base64 = signature or self._get_order_signature_base64()
        if not signature_base64:
            _logger.warning(
                "El pedido %s (%s) no tiene firma para enviar.",
                self.id, self.name
            )
            return False

        try:
            endpoint_url = settings.api_endpoint.rstrip('/')
            url = f'{endpoint_url}/orders/{self.id}/signature'
            
            headers = self._build_philco_headers(settings)
            payload = {
                'odoo_order_id': self.id,
                'odoo_order_name': self.name,
                'signature_image': signature_base64,
            }
            
            _logger.info(
                "Enviando notificación de firma a Philco Shop. "
                "Pedido: %s (%s) | URL: %s",
                self.id, self.name, url
            )
            response = requests.put(
                url,
                headers=headers,
                json=payload,
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code in (200, 201):
                _logger.info(
                    "Notificación de firma enviada exitosamente. "
                    "Pedido: %s (%s) | Status code: %d",
                    self.id, self.name, response.status_code
                )
                return True
            else:
                response_text = response.text[:200] if response.text else "(sin contenido)"
                _logger.warning(
                    "Respuesta inesperada de Philco Shop al enviar firma. "
                    "Pedido: %s (%s) | Status code: %d | Respuesta: %s",
                    self.id, self.name, response.status_code, response_text
                )
                return False
        except Exception as e:
            _logger.exception(
                "Error inesperado al notificar firma a Philco Shop. "
                "Pedido: %s (%s) | Detalles: %s",
                self.id, self.name, str(e)
            )
            return False
        


    # =========================================================================
    # La detección de cambios de estado se centraliza únicamente en write().
    # action_confirm(), action_cancel() y action_draft() de Odoo ya invocan
    # write() internamente, por lo que no es necesario duplicar la notificación.
    # =========================================================================

    """ def create(self, vals):
        
        Crea un nuevo pedido.
        No se notifica aquí porque es un pedido nuevo (draft).
        
        return super().create(vals)
    """
    def write(self, vals):
        """
        Intercepta cambios en el pedido para detectar cambios de estado.
        
        Si el campo 'state' está siendo modificado, detecta el cambio y notifica
        a Laravel después de que write() sea exitoso.
        
        Estrategia:
        - Si 'state' está en vals, extraemos el estado anterior
        - Ejecutamos escribir normalmente (super)
        - Si el estado cambió realmente, notificamos
        - Esto evita duplicados: una notificación por cambio real
        """
        # Verificar si está cambiando el estado
        state_in_vals = 'state' in vals
        signature_in_vals = 'signature' in vals
        old_states = {}
        
        if state_in_vals:
            # Guardar el estado anterior de cada registro
            for record in self:
                old_states[record.id] = record.state
        
        # Ejecutar write normalmente
        result = super().write(vals)
        
        # Si cambió el estado, notificar
        if state_in_vals:
            for record in self:
                new_state = record.state
                old_state = old_states.get(record.id)
                
                # Solo notificar si el estado cambió realmente
                if old_state != new_state:
                    _logger.info(
                        "Cambio de estado detectado en pedido %s (%s): %s -> %s",
                        record.id, record.name, old_state, new_state
                    )
                    try:
                        record._notify_philco_order_status(force=True)
                    except Exception as e:
                        # Modo tolerante: loguea pero no bloquea
                        _logger.exception(
                            "Error notificando cambio de estado en pedido %s: %s",
                            record.id, str(e)
                        )

        # Si cambió la firma, notificar a Laravel en modo tolerante.
        if signature_in_vals:
            for record in self:
                if not record.signature:
                    continue
                try:
                    record._notify_philco_order_signature()
                except Exception as e:
                    _logger.exception(
                        "Error notificando firma del pedido %s: %s",
                        record.id, str(e)
                    )
        
        return result
    
