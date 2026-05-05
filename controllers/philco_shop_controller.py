import requests
from odoo import http
from odoo.http import request


class PhilcoShopController(http.Controller):

    @http.route('/philco/product/live_stats/<int:product_tmpl_id>', type='json', auth='user', methods=['POST'], csrf=False)
    def philco_product_live_stats(self, product_tmpl_id):
        product = request.env['product.template'].sudo().browse(product_tmpl_id)

        if not product.exists():
            return {
                'success': False,
                'message': 'Producto no encontrado en Odoo.'
            }

        if not product.philco_product_id:
            return {
                'success': False,
                'message': 'El producto no tiene philco_product_id.'
            }

        settings = request.env['philco.conexion'].sudo().search([('active', '=', True)], limit=1)
        if not settings:
            return {
                'success': False,
                'message': 'No existe configuración activa de Philco Shop.'
            }

        try:
            headers = {
                'Accept': 'application/json',
                'Authorization': f'Bearer {settings.access_token}',
            }

            # Ejemplo: http://tiendasphilco.test/api/v1/product/6
            url = f"{settings.url_base}/api/v1/product/{product.philco_product_id}"

            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            data = response.json()
            print("Respuesta de Laravel:", data)
            
            if not data.get('success') or not data.get('product'):
                return {
                    'success': False,
                    'message': 'Respuesta inválida desde Laravel.',
                    'raw': data
                }

            product_data = data['product']

            values = {
                'philco_likes_count': product_data.get('likes_count', 0),
                'philco_shares_count': product_data.get('shares_count', 0),
                'philco_views_count': product_data.get('views_count', 0),
                'philco_sales_count': product_data.get('sales_count', 0),
                'philco_listing_url': product_data.get('slug') and f"{settings.url_base}/product/{product_data.get('slug')}" or False,
            }

            product.write(values)

            return {
                'success': True,
                'message': 'Métricas actualizadas correctamente.',
                'data': values
            }

        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'message': f'Error consultando Laravel: {str(e)}'
            }