from odoo import models, fields, api
import requests
import json
import base64
import imghdr
from odoo.exceptions import UserError



class ProductTemplate(models.Model):
    _inherit = 'product.template'

    philco_web_price = fields.Float(string="Precio regular Web", help="Precio del producto en Philco Shop")
    philco_stock = fields.Integer(string="Stock disponible", help="Stock disponible para la venta en Philco Shop")
    philco_product_id = fields.Char(string="Philco Shop ID", help="ID del producto en Philco Shop")
    philco_descripcion = fields.Char(string="Descripcion corta", help="descripcion en Philco Shop")
    philco_listing_url = fields.Char(string="URL del producto", help="URL de la publicación en Philco Shop")
   
    
    def action_check_product(self):
        #print en consola
        print("Enviando productos a Philco Shop...")
        url_base_tienda = "https://magento-192432-0.cloudclusters.net/"
        endpoint = "rest/V1/products/{}".format(self.barcode)
        url = url_base_tienda + endpoint
       
        for product in self:
            headers = {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer 0y9r0ltwxutpg0h9hhks9pazqkmtps6q'
            }
            
            #comprobar si el producto existe en magento
            get_url = f"{url_base_tienda}rest/V1/products/{product.barcode}"
            get_response = requests.get(get_url, headers=headers)
            
            if get_response.status_code == 200:
                 product.message_post(body=f"datos del producto en Philco Shop: {get_response.text}")
            else:
                print("El producto no existe en Philco Shop.")

    def action_send_to_philco_shop(self):
    
        settings = self.env['philco.conexion'].search([('active', '=', True)], limit=1)

        if not settings:
            raise UserError("No se encontró configuración activa para Philco Shop.")
        
        #url_base_tienda = "https://magento-192432-0.cloudclusters.net/"
        url_base_tienda = settings.url_base

       
        for product in self:
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {settings.access_token}'
            }
           
            product_image = product.image_512
            image_data = base64.b64decode(product_image)
            image_mime = imghdr.what(None, h=image_data)
            
            if image_mime == 'webp':
                image_data = ProductTemplate.convert_webp_to_jpg(image_data)
                image_mime = 'jpeg'
            exit()

            
            
            categories_selected = product.magento_category_ids.mapped('magento_id')

            payload ={
                        "product": {
                            "sku": product.barcode,
                            "name": product.name,
                            "price": product.philco_web_price,
                            "status": 1,
                            "category_ids": [str(cat_id) for cat_id in categories_selected],
                            "stock_data": {
                                "qty": product.philco_stock,
                                "is_in_stock": product.philco_stock > 0
                            },
                        },
                        
                    }

            if image_data:
                payload["product"]["media_gallery_entries"] = [{
                    "media_type": "image",
                    "label": product.name,
                    "position": 1,
                    "disabled": False,
                    "file": f"{product.barcode}.jpg",  # Nombre de archivo basado en SKU
                    "content": {
                        "base64_encoded_data": str(image_data),  # Convertir a cadena Base64
                        "type": image_mime,  # Tipo MIME de la imagen
                        "name": f"{product.barcode}.jpg"
                    }
                }]

            # Crear un nuevo producto
            #imprime el payload en consola
            print("Payload enviado a Philco Shop:", json.dumps(payload, indent=4))
           
            url = f"{url_base_tienda}/rest/all/V1/products"       # con all crear registro para store_id=0
            response = requests.post(url, data=json.dumps(payload), headers=headers)
           

        
            if response.status_code == 200 or response.status_code == 201:
             
                product_data = response.json()
                print("Producto creado en Philco Shop:", product_data)

                product_id = product_data.get('id')
                if product_id:
                    product.magento_id = product_id  
                
                url_key = None
                for attribute in product_data.get('custom_attributes', []):
                    if attribute.get('attribute_code') == 'url_key':
                        url_key = attribute.get('value')
                        break

                if url_key:
                    url_producto = f"{url_base_tienda}{url_key}.html"
                    product.magento_listing_url = url_producto
                
                product.magento_status = 'active'
                product.message_post(body="Producto creado en Philco Shop con éxito.")

            else:
                product.message_post(body=f"Error al enviar a Philco Shop: {response.text}")
    
   