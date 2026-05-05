import base64
import binascii
import logging

from odoo import models
from odoo.exceptions import UserError
from odoo.tools import image_process
from odoo.tools.mimetypes import guess_mimetype

_logger = logging.getLogger(__name__)

class PhilcoApiMixin(models.AbstractModel):
    _name = 'philco.api.mixin'
    _description = 'Philco API helper methods'

    def _get_philco_settings(self):
        settings = self.env['philco.conexion'].search(
            [('active', '=', True)], limit=1
        )
        if not settings:
            raise UserError(
                "No se encontró configuración activa para Philco Shop. "
                "Ve a Configuración → Philco Conexión y activa una."
            )
        return settings

    def _build_philco_headers(self, settings, include_accept=False):
        headers = {
            'Authorization': f'Bearer {settings.access_token}',
            'Content-Type': 'application/json',
        }
        if include_accept:
            headers['Accept'] = 'application/json'
        return headers

    def _optimize_image_for_upload(self, image_base64, max_width=0, max_height=0):
        """
        Optimiza una imagen usando la función de Odoo: redimensiona y convierte a WebP.
        
        Cuando Odoo guarda un campo Image, ya está optimizado a WebP.
        Este método solo procesa si es necesario (imágenes nuevas, no WebP, etc).
        
        :param image_base64: imagen desde campo Image de Odoo (bytes o str en base64)
        :param max_width: ancho máximo en píxeles (0 = sin límite)
        :param max_height: alto máximo en píxeles (0 = sin límite)
        :return: imagen optimizada en base64 string
        """
        if not image_base64:
            return None
        
        try:
            # Los campos Image de Odoo devuelven bytes del STRING base64
            # Primero convertir a string si son bytes
            if isinstance(image_base64, bytes):
                base64_str = image_base64.decode('utf-8')
            else:
                base64_str = image_base64
            
            if not base64_str:
                return None
            
            # Ahora decodificar el base64 para obtener los bytes REALES de la imagen
            img_bytes = base64.b64decode(base64_str)
            
            if not img_bytes:
                return None
            
            # Detectar tipo MIME de la imagen (sin decodificar todo)
            mime_type = guess_mimetype(img_bytes, '')
            
            # Si es SVG, devolverlo sin procesar (ya está OK)
            if mime_type == 'image/svg+xml':
                _logger.debug("SVG detectado, devolviendo sin procesar")
                return base64_str
            
            # Si ya es WebP, Odoo ya lo optimizó - devolver sin procesar
            if mime_type == 'image/webp':
                _logger.debug("WebP detectado (ya optimizado por Odoo), devolviendo sin procesar")
                return base64_str
            
            # Para otros formatos (JPEG, PNG, GIF), procesar y convertir a WebP
            _logger.debug(f"Procesando imagen {mime_type} con image_process")
            optimized = image_process(
                img_bytes,
                size=(max_width, max_height),
                verify_resolution=True,
                quality=80,  # Calidad WebP (0-100), 80 es buen compromiso
            ) or b''
            
            # Retornar en base64
            if optimized:
                b64_result = base64.b64encode(optimized).decode('utf-8')
                _logger.info(f"Imagen optimizada: {len(img_bytes)} -> {len(optimized)} bytes")
                return b64_result
            else:
                return None
            
        except (binascii.Error, ValueError) as e:
            _logger.warning(f"Error al decodificar base64: {str(e)}")
            # Si falla el decode, intentar devolver el string original
            if isinstance(image_base64, bytes):
                try:
                    return image_base64.decode('utf-8')
                except:
                    return None
            return str(image_base64) if image_base64 else None
        
        except Exception as e:
            # Si falla la optimización, registrar y devolver la original
            _logger.warning(f"Error al optimizar imagen: {str(e)}")
            # Intentar devolver el valor original como string base64
            if isinstance(image_base64, bytes):
                try:
                    return image_base64.decode('utf-8')
                except:
                    return None
            return str(image_base64) if image_base64 else None
