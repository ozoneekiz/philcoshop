from odoo import models, fields
from odoo.exceptions import UserError
import requests

class PhilcoWebOrder(models.Model):
    _name = "philco.web.order"
    _description = "Pedidos importados desde philcoshop"

    order_id = fields.Integer(string="id de pedido", required=True)
    customername = fields.Char(string="cliente", required=True)
    is_active = fields.Boolean(string="Activo", default=True)
    total = fields.Float(string="Total")
    status = fields.Char(string="Estado")
    

    def importar_pedidos_philco(self):
        settings = self.env['philco.conexion'].search([('active', '=', True)], limit=1)

        if not settings:
            raise UserError("No se encontró configuración activa para philcoshop. Por favor, configure la conexión antes de importar categorías.")
        
        url_base_tienda = settings.url_base

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {settings.access_token}'
        }
        url = f"{url_base_tienda}/api/V1/orders"

        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            

            pedidos = response.json()
            count = self._importar_pedidos(pedidos, "")

            return [
                {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Importación de Pedidos',
                        'message': f'Se han importado {count} pedidos desde PhilcoShop.',
                        'type': 'success',
                        'sticky': False,
                    }
                },
                {
                    'type': 'ir.actions.client',
                    'tag': 'reload',  # Recarga la vista automáticamente
                    
                }
            ]
        else:
            raise UserError(f"Error al obtener los pedidos: {response.status_code}\n{response.text}")

    def _importar_pedidos(self, pedidos, parent_name):
        count = 0
        #full_name = f"{parent_name} / {category_data['name']}" if parent_name else category_data['name']
        
        self.create({
            'order_id': pedidos['entity_id'],
            'customername': pedidos['customer_firstname'] + " " + pedidos['customer_lastname'],
            'total': pedidos['grand_total'],
        })
        count += 1

        
        
        return count
