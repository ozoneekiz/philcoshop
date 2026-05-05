import json
import logging
import time

import requests

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Caché a nivel de proceso: sobrevive entre requests del mismo worker
# { philco_product_id: (timestamp, dict_de_datos, mensaje_error) }
_PHILCO_PROCESS_CACHE: dict = {}
_PHILCO_CACHE_TTL = 10  # segundos

# Buffer temporal para productos nuevos (sin philco_product_id aún).
# Cuando el inverso corre durante el save, el ORM todavía tiene el valor del
# usuario. Lo guardamos aquí y _build_payload lo lee antes del POST.
# { odoo_product_template_id: {'stock': int, 'descripcion': str, 'video_url': str, 'slug': str} }
_PHILCO_PENDING_VALUES: dict = {}


class ProductTemplate(models.Model):
    _name = 'product.template'
    _inherit = ['product.template', 'philco.api.mixin']

    # =========================================================================
    # Campos store=True — se guardan en Odoo (filtrables, fuente de verdad)
    # =========================================================================

    philco_product_id = fields.Integer(
        string="Philco Shop ID",
        copy=False,
        help="ID del producto en Philco Shop.",
    )
    philco_listing_url = fields.Char(
        string="URL del producto",
        copy=False,
        help="URL de la publicación en Philco Shop.",
    )
    philco_vertical_image = fields.Image(
        string="Imagen vertical Philco Shop",
        max_width=1080,
        max_height=1920,
    )

    # Reemplaza philco_is_active_db — un solo campo, store=True, filtrable
    philco_is_active = fields.Boolean(
        string="Activo en tienda",
        store=True,
        default=False,
        copy=False,
        help="Controla si el producto es visible en Philco Shop. "
             "Se guarda en Odoo para poder filtrar productos por estado.",
        inverse='_inverse_philco_is_active',
    )

    # store=True para recordar si tiene precio web propio
    philco_web_price = fields.Float(
        string="Precio regular Web",
        store=True,
        default=0.0,
        copy=False,
        help="Precio que se muestra en la tienda. "
             "Si es 0 se usa el precio de lista de Odoo.",
        inverse='_inverse_philco_web_price',
    )

    philco_last_sync_at = fields.Datetime(
        string="Ultima sincronizacion Philco",
        readonly=True,
        copy=False,
        help="Fecha/hora del ultimo ENVIO exitoso de datos hacia Philco Shop.",
    )

    # Galería de imágenes para la tienda web
    philco_image_ids = fields.One2many(
        'philco.product.image',
        'product_tmpl_id',
        string="Imágenes Philco Shop",
        copy=False,
    )

    # =========================================================================
    # Campos compute — vienen de Laravel via GET, NO se guardan en Odoo
    # =========================================================================

    philco_is_new = fields.Boolean(
        string="Es nuevo",
        compute='_compute_philco_data',
        inverse='_inverse_philco_is_new',
    )
    philco_is_on_sale = fields.Boolean(
        string="En oferta",
        compute='_compute_philco_data',
        inverse='_inverse_philco_is_on_sale',
    )
    philco_is_featured = fields.Boolean(
        string="Destacado",
        compute='_compute_philco_data',
        inverse='_inverse_philco_is_featured',
    )
    philco_discount_price = fields.Float(
        string="Precio oferta Web",
        help="Precio de oferta (0 = sin oferta).",
        compute='_compute_philco_data',
        inverse='_inverse_philco_discount_price',
    )
    philco_stock = fields.Integer(
        string="Stock disponible",
        compute='_compute_philco_data',
        inverse='_inverse_philco_stock',
    )
    philco_descripcion = fields.Char(
        string="Descripción corta",
        compute='_compute_philco_data',
        inverse='_inverse_philco_descripcion',
    )
    philco_video_url = fields.Char(
        string="URL del video",
        compute='_compute_philco_data',
        inverse='_inverse_philco_video_url',
        help="URL de YouTube o Vimeo del video del producto.",
    )
    philco_slug = fields.Char(
        string="Slug",
        compute='_compute_philco_data',
        inverse='_inverse_philco_slug',
        help="Slug del producto en Philco Shop.",
    )

    # Métricas — solo lectura desde Laravel, no se editan desde Odoo
    philco_likes_count = fields.Integer(
        string="Likes",
        compute='_compute_philco_data',
    )
    philco_shares_count = fields.Integer(
        string="Compartidos",
        compute='_compute_philco_data',
    )
    philco_views_count = fields.Integer(
        string="Vistas",
        compute='_compute_philco_data',
    )
    philco_sales_count = fields.Integer(
        string="Ventas web",
        compute='_compute_philco_data',
    )
    philco_api_message = fields.Char(
        string="Estado de sincronizacion Philco",
        compute='_compute_philco_data',
    )

    # =========================================================================
    # Helpers de conversión de tipos
    # =========================================================================

    def _safe_float(self, value, default=0.0):
        try:
            if value in (None, False, ''):
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def _safe_int(self, value, default=0):
        try:
            if value in (None, False, ''):
                return default
            return int(float(value))
        except (TypeError, ValueError):
            return default

    def _display_notification(self, message, notif_type='warning', sticky=True):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Philco Shop',
                'message': message,
                'type': notif_type,
                'sticky': sticky,
            },
        }

    # =========================================================================
    # Compute — GET a Laravel para campos que NO se guardan en Odoo
    # philco_is_active y philco_web_price ya NO están aquí (son store=True)
    # =========================================================================

    @api.depends('philco_product_id')
    def _compute_philco_data(self):
        """
        Trae desde Laravel los campos que no se guardan en Odoo:
        flags de visibilidad, precio oferta, stock, descripción,
        video y métricas.
        philco_is_active y philco_web_price quedan fuera porque
        son store=True y Odoo es su fuente de verdad.
        """
        _logger.debug("_compute_philco_data para: %s", self.mapped('name'))

        settings = self.env['philco.conexion'].search(
            [('active', '=', True)], limit=1
        )

        for product in self:
            # Valores por defecto
            product.philco_is_new         = False
            product.philco_is_on_sale     = False
            product.philco_is_featured    = False
            product.philco_discount_price = 0.0
            product.philco_likes_count    = 0
            product.philco_shares_count   = 0
            product.philco_views_count    = 0
            product.philco_sales_count    = 0
            product.philco_api_message    = False
            product.philco_slug           = ''

            if not product.philco_product_id:
                continue

            if not settings:
                product.philco_api_message = (
                    "No hay una configuracion activa de Philco Shop."
                )
                continue

            pid = product.philco_product_id
            now = time.monotonic()
            cached = _PHILCO_PROCESS_CACHE.get(pid)

            if cached and (now - cached[0]) < _PHILCO_CACHE_TTL:
                data = cached[1]
                error_message = cached[2]
                _logger.info("Usando caché para '%s' (ID %s).", product.name, pid)
            else:
                try:
                    headers = self._get_api_headers(settings)
                    url = f"{settings.api_endpoint}/products/{pid}"
                    response = requests.get(url, headers=headers, timeout=10)
                    response.raise_for_status()
                    print(response)
                    data = response.json().get('product', {})
                    error_message = False
                    _PHILCO_PROCESS_CACHE[pid] = (now, data, error_message)
                    _logger.info("Datos cargados desde Laravel para '%s'.", product.name)
                except requests.exceptions.HTTPError as e:
                    if e.response.status_code == 404:
                        error_message = (
                            "Philco Shop no encontro este producto. "
                            "Se mantiene el vinculo local."
                        )
                    else:
                        error_message = (
                            f"Philco Shop devolvio un error HTTP {e.response.status_code}."
                        )
                    _logger.warning(
                        "Error HTTP %s al cargar '%s': %s",
                        e.response.status_code, product.name, str(e),
                    )
                    data = {}
                    _PHILCO_PROCESS_CACHE[pid] = (now, data, error_message)
                except Exception as e:
                    error_message = "Philco Shop no responde. Intenta nuevamente."
                    _logger.warning("Error Philco para '%s': %s", product.name, str(e))
                    data = {}
                    _PHILCO_PROCESS_CACHE[pid] = (now, data, error_message)

            product.philco_api_message = error_message

            p = data
            if not p:
                continue

            product.philco_is_new         = bool(p.get('is_new', False))
            product.philco_is_on_sale     = bool(p.get('is_on_sale', False))
            product.philco_is_featured    = bool(p.get('is_featured', False))
            product.philco_discount_price = self._safe_float(p.get('discount_price'))
            product.philco_stock          = self._safe_int(p.get('stock'))
            product.philco_descripcion    = p.get('description') or ''
            product.philco_video_url      = p.get('video_url') or ''
            product.philco_slug           = p.get('slug') or ''
            product.philco_likes_count    = self._safe_int(p.get('likes_count'))
            product.philco_shares_count   = self._safe_int(p.get('shares_count'))
            product.philco_views_count    = self._safe_int(p.get('views_count'))
            product.philco_sales_count    = self._safe_int(p.get('sales_count'))

            

    # =========================================================================
    # write() override — sincroniza tags y list_price automáticamente
    # =========================================================================

    def write(self, vals):
        result = super().write(vals)

        # --- Tags (M2M sin inverse propio) -----------------------------------
        if 'product_tag_ids' in vals:
            for product in self:
                if not product.philco_product_id:
                    continue
                try:
                    settings = product._get_philco_settings()
                    headers = product._get_api_headers(settings)
                    url = f"{settings.api_endpoint}/products/{product.philco_product_id}"
                    payload = {
                        "product": {
                            "tags": product.product_tag_ids.mapped('name')
                        }
                    }
                    requests.put(
                        url,
                        data=json.dumps(payload),
                        headers=headers,
                        timeout=10,
                    ).raise_for_status()
                    _PHILCO_PROCESS_CACHE.pop(product.philco_product_id, None)
                    product.philco_last_sync_at = fields.Datetime.now()
                    
                except Exception as e:
                    _logger.warning(
                        "No se sincronizaron tags de '%s': %s", product.name, str(e)
                    )

        # --- list_price: solo si no tiene philco_web_price propio ------------
        if 'list_price' in vals:
            for product in self:
                if not product.philco_product_id:
                    continue
                if product.philco_web_price:
                    """ _logger.info(
                        "list_price cambió en '%s' pero tiene philco_web_price. "
                        "No se actualiza la tienda.", product.name,
                    ) """
                    continue
                try:
                    settings = product._get_philco_settings()
                    headers = product._get_api_headers(settings)
                    url = f"{settings.api_endpoint}/products/{product.philco_product_id}"
                    payload = {"product": {"price": product.list_price}}
                    requests.put(
                        url,
                        data=json.dumps(payload),
                        headers=headers,
                        timeout=10,
                    ).raise_for_status()
                    _PHILCO_PROCESS_CACHE.pop(product.philco_product_id, None)
                    product.philco_last_sync_at = fields.Datetime.now()
                    
                except Exception as e:
                    _logger.warning(
                        "No se sincronizó list_price de '%s': %s", product.name, str(e)
                    )

        return result

    # =========================================================================
    # Inverses
    # =========================================================================

    def _inverse_philco_is_active(self):
        """store=True — el valor ya está en Odoo, solo hay que enviarlo a Laravel."""
        self._patch_philco_field('is_active', 'philco_is_active')

    def _inverse_philco_web_price(self):
        """store=True — si es 0 envía list_price como fallback."""
        for product in self:
            if not product.philco_web_price:
                product._patch_philco_field('price', 'list_price')
            else:
                product._patch_philco_field('price', 'philco_web_price')

    def _inverse_philco_is_new(self):
        self._patch_philco_field('is_new', 'philco_is_new')

    def _inverse_philco_is_on_sale(self):
        self._patch_philco_field('is_on_sale', 'philco_is_on_sale')

    def _inverse_philco_is_featured(self):
        self._patch_philco_field('is_featured', 'philco_is_featured')

    def _inverse_philco_discount_price(self):
        self._patch_philco_field('discount_price', 'philco_discount_price')

    def _inverse_philco_stock(self):
        for product in self:
            if product.philco_product_id:
                product._patch_philco_field('stock', 'philco_stock')
            else:
                _PHILCO_PENDING_VALUES.setdefault(product.id, {})['stock'] = product.philco_stock

    def _inverse_philco_descripcion(self):
        for product in self:
            if product.philco_product_id:
                product._patch_philco_field('description', 'philco_descripcion')
            else:
                _PHILCO_PENDING_VALUES.setdefault(product.id, {})['descripcion'] = product.philco_descripcion

    def _inverse_philco_video_url(self):
        for product in self:
            if product.philco_product_id:
                product._patch_philco_field('video_url', 'philco_video_url')
            else:
                _PHILCO_PENDING_VALUES.setdefault(product.id, {})['video_url'] = product.philco_video_url

    def _inverse_philco_slug(self):
        for product in self:
            if product.philco_product_id:
                product._patch_philco_field('slug', 'philco_slug')
            else:
                _PHILCO_PENDING_VALUES.setdefault(product.id, {})['slug'] = product.philco_slug

    def _patch_philco_field(self, laravel_key, odoo_field):
        """
        Envía a Laravel SOLO el campo que cambió (PUT parcial).
        Funciona con campos escalares (bool, int, float, str).
        Para M2M como product_tag_ids usar el write() override.
        """
        for product in self:
            if not product.philco_product_id:
                continue
            try:
                settings = self._get_philco_settings()
                headers = self._get_api_headers(settings)
                url = f"{settings.api_endpoint}/products/{product.philco_product_id}"
                payload = {"product": {laravel_key: getattr(product, odoo_field)}}
                
                response = requests.put(
                    url,
                    data=json.dumps(payload),
                    headers=headers,
                    timeout=10,
                )
                response.raise_for_status()
                _PHILCO_PROCESS_CACHE.pop(product.philco_product_id, None)
                product.philco_last_sync_at = fields.Datetime.now()
                _logger.info(
                    "Campo '%s' actualizado en Laravel para '%s'.",
                    laravel_key, product.name,
                )
            except Exception as e:
                _logger.warning(
                    "No se pudo actualizar '%s' en Laravel para '%s': %s",
                    laravel_key, product.name, str(e),
                )

    # =========================================================================
    # Helpers privados
    # =========================================================================

    def _get_api_headers(self, settings):
        return self._build_philco_headers(settings, include_accept=True)

    def _get_image_base64(self, image_field, max_width=0, max_height=0):
        """
        Convierte un campo Image a data URI WebP, optimizando la imagen.
        
        Acepta cualquier campo Image, no solo el vertical.
        :param image_field: valor binario del campo Image
        :param max_width: ancho máximo para optimizar (ej: 1080 para vertical)
        :param max_height: alto máximo para optimizar (ej: 1920 para vertical)
        """
        if not image_field:
            return None
        
        # Optimizar usando el método del mixin
        optimized = self._optimize_image_for_upload(image_field, max_width, max_height)
        
        if not optimized:
            return None
        
        return f"data:image/webp;base64,{optimized}"

    def _build_gallery_payload(self):
        """
        Construye el array de imágenes de la galería en base64.
        Devuelve lista ordenada por sequence.
        Optimiza cada imagen para reducir tamaño.
        """
        self.ensure_one()
        images = []
        for img_record in self.philco_image_ids.sorted('sequence'):
            # Optimizar imagen de galería (max 1920x1920)
            b64 = self._get_image_base64(img_record.image, max_width=1920, max_height=1920)
            if b64:
                images.append({
                    "base64": b64,
                    "sequence": img_record.sequence,
                    "name": img_record.name or '',
                })
        return images

    def _build_payload(self, include_image=False, include_gallery=False):
        """
        Payload completo del producto.
        include_image   → incluye imagen vertical
        include_gallery → incluye galería de imágenes web
        """
        self.ensure_one()

        string_tags = self.product_tag_ids.mapped('name')
        uom_prices = self.multi_uom_price_ids.mapped(
            lambda r: {
                "uom_name": r.uom_id.display_name,
                "price": r.price,
                "units_in_pack": r.uom_id.factor_inv,
            }
        )
        categories = self.categ_id.mapped(lambda r: r.display_name)
        Product_variants = []

        #si el porducto tiene atributos, se agregan al payload
        if self.attribute_line_ids:
            for line in self.attribute_line_ids:
                variant = []
                for value in line.value_ids:
                    value_data = {
                        "name": value.name,
                        "html_color": value.html_color,
                    }

                    if line.attribute_id.create_variant:
                        variants = self.product_variant_ids.filtered(
                            lambda v: value in v.product_template_attribute_value_ids.mapped(
                                'product_attribute_value_id'
                            )
                        )
                        value_data["barcode"] = variants[:1].barcode or ''
                        value_data["id"] = variants[:1].id,
                        
                        

                    variant.append(value_data)

                if variant:
                    Product_variants.append({
                        "attribute_name": line.attribute_id.display_name,
                        
                        "variants": variant,
                    })
           

        # Para el POST inicial usamos el valor editable del formulario.
        # Los inversos guardan el valor en _PHILCO_PENDING_VALUES antes de que
        # el compute lo resetee durante el RPC del botón.
        pending = _PHILCO_PENDING_VALUES.get(self.id, {})

        stock_value = self._safe_int(pending.get('stock', self.philco_stock))
        if stock_value <= 0:
            #stock_value = self._safe_int(self.qty_available)
            #indicar que el campo es requerido
            raise UserError(
                f"El producto '{self.name}' necesita un stock mayor a 0 para publicarlo en Philco Shop."
            )
        # si el peodurto no tiene barcode y no tiene atributo
        if not self.barcode  and not self.attribute_line_ids:
            raise UserError(
                f"El producto '{self.name}' necesita un código de barras para publicarlo en Philco Shop."
            )
        description_value = (
            (pending.get('descripcion') or self.philco_descripcion or '').strip()
            or (self.description_sale or '').strip()
            or (self.description or '').strip()
        )

        video_value = (pending.get('video_url') or self.philco_video_url or '').strip()
        slug_value = (pending.get('slug') or self.philco_slug or '').strip()

        product_payload = {
            "odoo_id":         self.id,
            "sku":             self.barcode,
            "name":            self.name,
            "price":           self.philco_web_price or self.list_price,
            "discount_price":  self.philco_discount_price or 0,
            "stock":           stock_value,
            "description":     description_value,
            "video_url":       video_value,
            "slug":            slug_value,
            "is_active":       self.philco_is_active,
            "is_new":          self.philco_is_new,
            "is_on_sale":      self.philco_is_on_sale,
            "is_featured":     self.philco_is_featured,
            "tags": string_tags,
            "uom_prices":      (uom_prices),
            "category":        (categories),
            "product_variants":  Product_variants,
        }

        if include_image:
            img = self._get_image_base64(
                self.philco_vertical_image or self.image_1920,
                max_width=1080,
                max_height=1920
            )
            if not img:
                raise UserError(
                    f"El producto '{self.name}' necesita al menos una imagen "
                    "para enviarlo a Philco Shop."
                )
            product_payload["imageBase64"] = img

        if include_gallery:
            gallery = self._build_gallery_payload()
            if gallery:
                product_payload["gallery"] = gallery

        return {"product": product_payload}

    def _call_api(self, method, url, headers, payload=None):
        """Wrapper HTTP centralizado con mensajes de error legibles."""
        try:
            response = requests.request(
                method,
                url,
                data=json.dumps(payload) if payload else None,
                headers=headers,
                timeout=15,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError:
            raise UserError(
                "No se pudo conectar con Philco Shop. "
                "Verifica que la URL base esté correcta."
            )
        except requests.exceptions.Timeout:
            raise UserError(
                "La solicitud a Philco Shop tardó demasiado (timeout). "
                "Intenta nuevamente."
            )
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code
            detail = e.response.text[:300]
            raise UserError(f"Error HTTP {status} en Philco Shop:\n{detail}")

    # =========================================================================
    # Acciones de botones
    # =========================================================================

    def action_send_to_philco_shop(self):
        """Crea el producto en Philco Shop (POST) con imagen vertical y galería."""
        try:
            settings = self._get_philco_settings()
        except UserError as e:
            return self._display_notification(str(e))

        for product in self:
            if product.philco_product_id:
                return self._display_notification(
                    f"'{product.name}' ya existe en Philco Shop "
                    f"(ID: {product.philco_product_id}). "
                    "Usa el botón 'Actualizar' en su lugar.",
                )

            try:
                headers = self._get_api_headers(settings)
                payload = product._build_payload(
                    include_image=True,
                    include_gallery=True,
                )
                
                response = self._call_api(
                    'POST', f"{settings.api_endpoint}/products", headers, payload
                )
                
            except UserError as e:
                return self._display_notification(str(e))

            p = response.get('product', {})
            
            if p.get('id'):
                product.philco_product_id = p['id']
                self.philco_is_active = True  # Se activa al publicar
            if p.get('slug'):
                product.philco_listing_url = f"{settings.url_base}/{p['slug']}"
            
            # Limpiar el buffer temporal — ya tiene philco_product_id
            _PHILCO_PENDING_VALUES.pop(product.id, None)
            product.philco_last_sync_at = fields.Datetime.now()

            
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'product.template',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_update_product(self):
        """Actualiza todos los campos del producto en Philco Shop (sin imágenes)."""
        for product in self:
            if not product.philco_product_id:
                return self._display_notification(
                    f"'{product.name}' no tiene ID de Philco Shop. "
                    "Primero publícalo usando 'Enviar a Philco Shop'.",
                )

            try:
                settings = self._get_philco_settings()
                headers = self._get_api_headers(settings)
                payload = product._build_payload(
                    include_image=False,
                    include_gallery=False,
                )
                url = f"{settings.api_endpoint}/products/{product.philco_product_id}"
                response = self._call_api('PUT', url, headers, payload)
                print(f"Respuesta de actualización para '{product.name}': {response}")
                product.philco_last_sync_at = fields.Datetime.now()
                _PHILCO_PROCESS_CACHE.pop(product.philco_product_id, None)
            except UserError as e:
                print(f"Error al actualizar '{product.name}': {str(e)}")
                return self._display_notification(str(e))

            _logger.info("Producto '%s' actualizado en Philco Shop.", product.name)

        return self._display_notification(
            "Producto actualizado correctamente. 2",
            notif_type='success',
            sticky=False,
        )

    def action_update_image(self):
        """Actualiza solo la imagen vertical del producto en Philco Shop."""
        for product in self:
            if not product.philco_product_id:
                raise UserError(f"'{product.name}' no está publicado en Philco Shop.")
            try:
                settings = self._get_philco_settings()
                headers = self._get_api_headers(settings)
                img = product._get_image_base64(
                    product.philco_vertical_image or product.image_1920,
                    max_width=1080,
                    max_height=1920
                )
                if not img:
                    return self._display_notification(
                        f"'{product.name}' no tiene imagen para enviar."
                    )
                payload = {"imageBase64": img}
                url = f"{settings.api_endpoint}/products/{product.philco_product_id}/update_image"
                self._call_api('PUT', url, headers, payload)
                product.philco_last_sync_at = fields.Datetime.now()
                _logger.info("Imagen vertical de '%s' actualizada.", product.name)
            except UserError as e:
                return self._display_notification(str(e))

        return self._display_notification(
            "Imagen vertical actualizada correctamente.",
            notif_type='success',
            sticky=False,
        )

    def action_update_gallery(self):
        """Actualiza solo la galería de imágenes en Philco Shop."""
        for product in self:
            if not product.philco_product_id:
                raise UserError(f"'{product.name}' no está publicado en Philco Shop.")

            if not product.philco_image_ids:
                return self._display_notification(
                    f"'{product.name}' no tiene imágenes en la galería."
                )

            try:
                settings = self._get_philco_settings()
                headers = self._get_api_headers(settings)
                gallery = product._build_gallery_payload()
                payload = {"product": {"gallery": gallery}}
                url = f"{settings.api_endpoint}/products/{product.philco_product_id}"
                self._call_api('PUT', url, headers, payload)
                product.philco_last_sync_at = fields.Datetime.now()
                _PHILCO_PROCESS_CACHE.pop(product.philco_product_id, None)
                _logger.info(
                    "Galería de '%s' actualizada (%d imágenes).",
                    product.name, len(gallery),
                )
            except UserError as e:
                return self._display_notification(str(e))

        return self._display_notification(
            "Galería actualizada correctamente.",
            notif_type='success',
            sticky=False,
        )

    def action_unpublish_from_philco(self):
        """Desactiva el producto , eliminando los datos de philcoshop_id y philco_listing_url."""
        for product in self:
            if not product.philco_product_id:
                raise UserError(f"'{product.name}' no tien id de Philco Shop.")
            product.philco_product_id = None
            product.philco_listing_url = None

    #si el self.name cambia, se actualiza el nombre en philco shop
    @api.onchange('name')
    def _onchange_name(self):
        for product in self:
            if product.philco_product_id:
                try:
                    settings = self._get_philco_settings()
                    headers = self._get_api_headers(settings)
                    url = f"{settings.api_endpoint}/products/{product.philco_product_id}"
                    payload = {"product": {"name": product.name}}
                    requests.put(
                        url,
                        data=json.dumps(payload),
                        headers=headers,
                        timeout=10,
                    ).raise_for_status()
                    _PHILCO_PROCESS_CACHE.pop(product.philco_product_id, None)
                    product.philco_last_sync_at = fields.Datetime.now()
                    _logger.info(
                        "Nombre sincronizado para '%s': %s",
                        product.name, product.name,
                    )
                except Exception as e:
                    _logger.warning(
                        "No se sincronizó el nombre de '%s': %s", product.name, str(e)
                    )
