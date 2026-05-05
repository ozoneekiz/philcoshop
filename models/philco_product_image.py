import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class PhilcoProductImage(models.Model):
    """
    Álbum de imágenes exclusivo para Philco Shop.
    Separado de las imágenes nativas de Odoo (product.image).
    Odoo convierte automáticamente a WebP al guardar el campo Image.
    """
    _name = 'philco.product.image'
    _description = 'Imagen Philco Shop'
    _order = 'sequence, id'

    # =========================================================================
    # Campos
    # =========================================================================

    product_tmpl_id = fields.Many2one(
        'product.template',
        string="Producto",
        required=True,
        ondelete='cascade',
        index=True,
    )
    name = fields.Char(
        string="Nombre / descripción",
        help="Opcional. Útil para identificar la imagen en la galería.",
    )
    image = fields.Image(
        string="Imagen",
        required=True,
        max_width=1920,
        max_height=1920,
        help="Odoo convierte y optimiza automáticamente a WebP al guardar.",
    )
    sequence = fields.Integer(
        string="Orden",
        default=10,
        help="Arrastra las filas para reordenar las imágenes en la tienda.",
    )

    # =========================================================================
    # Compute: nombre automático si no se pone uno
    # =========================================================================

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if not record.name:
                record.name = f"Imagen {record.id}"
        return records
