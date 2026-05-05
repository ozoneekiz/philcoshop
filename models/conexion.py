import token

from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
from urllib.parse import urlparse

class PhilcoConexion(models.Model):
    _name = "philco.conexion"
    _description = "Conexion con Philco Shop"

    name = fields.Char(string="Nombre de la Tienda", required=True)
    url_base = fields.Char(string="URL de tienda", required=True)
    api_endpoint = fields.Char(string="Endpoint de la API", required=True)
    whatsapp_number = fields.Char(string="Número de WhatsApp", required=True)
    access_token = fields.Char(string="Token de api philco shop", required=True)
    active = fields.Boolean(string="Activo", default=True)
    days_to_expire = fields.Integer(string="Días para expirar la url", default=7)
    url_shared = fields.Char(string="URL para compartir")
    expire_date = fields.Char(string="Fecha de expiración del url", store=True)


    def verificar_conexion(self):
        self.ensure_one()
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
        try:
            response = requests.get(f'{self.api_endpoint}/status', headers=headers)
            print(response)
            """  return response()->json([
            'success' => true,
            'message' => 'API está funcionando correctamente.',
             ]); """
            if response.json().get('success') == True:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Conexión Exitosa',
                        'message': 'La conexión con Philco Shop se ha verificado correctamente.',
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                raise UserError(_('Error de conexión: El servidor respondió con código %s. Verifica tus credenciales.') % response.status_code)
        except requests.exceptions.RequestException as e:
            raise UserError(_('Error de conexión: No se pudo conectar a Philco Shop. Error: %s') % str(e))
        except UserError:
            raise
        except Exception as e:
            raise UserError(_('Error inesperado al verificar la conexión: %s') % str(e))
    def crear_empresa(self):
        self.ensure_one()
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
        payload = {
            'name': self.name,
            'whatsapp_number': self.whatsapp_number
        }
        try:
            response = requests.post(f'{self.api_endpoint}/company', json=payload, headers=headers)
            print(payload)
            print(response)
            if response.status_code == 201:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Empresa creada',
                        'message': 'Empresa creada correctamente en Philco Shop.',
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                raise UserError(_('Error al crear la empresa: El servidor respondió con código %s. Mensaje: %s') % (response.status_code, response.json().get('message', '')))
        except requests.exceptions.RequestException as e:
            raise UserError(_('Error de conexión al crear la empresa: No se pudo conectar a Philco Shop. Error: %s') % str(e))
        except UserError:
            raise
        except Exception as e:
            raise UserError(_('Error inesperado al crear la empresa: %s') % str(e))
          
    def actualizar_whatsapp_number(self):
        self.ensure_one()
        for record in self:
            if record.active:
                # Verificar que el número de WhatsApp no esté vacío
                if not record.whatsapp_number:
                    raise UserError(_('El número de WhatsApp no puede estar vacío. Por favor, ingresa un número válido.'))
                # hacer una post con el numero de whatsapp

                headers = { 
                    'Authorization': f'Bearer {record.access_token}',
                    'Content-Type': 'application/json'
                }
                payload = {
                    'whatsapp_number': record.whatsapp_number
                }
                try:
                    response = requests.post(f'{record.api_endpoint}/update_whatsapp', json=payload, headers=headers)
                    if response.status_code == 200:
                        return {
                            'type': 'ir.actions.client',
                            'tag': 'display_notification',
                            'params': {
                                'title': 'WhatsApp actualizado',
                                'message': 'Número de WhatsApp actualizado correctamente en Philco Shop.',
                                'type': 'success',
                                'sticky': False,
                            }
                        }
                    else:
                        raise UserError(_('Error al actualizar el número de WhatsApp: El servidor respondió con código %s. Verifica tus credenciales.') % response.status_code)
                except requests.exceptions.RequestException as e:
                    raise UserError(_('Error de conexión al actualizar el número de WhatsApp: No se pudo conectar a Philco Shop. Error: %s') % str(e))
                except UserError:
                    raise
                except Exception as e:
                    raise UserError(_('Error inesperado al actualizar el número de WhatsApp: %s') % str(e))
     # obtener la url para compartir y guardarlo en url sahred api endpoint - Route::get('/token' ...
    def get_url_shared(self):
        for record in self:
            if record.active:
                try:
                    headers = {
                        'Authorization': f'Bearer {record.access_token}',
                        'Content-Type': 'application/json',
                        'Accept': 'application/json'
                    }
                    url = f'{record.api_endpoint}/token/{record.days_to_expire}'
                    print(url)
                    response = requests.post(url, headers=headers)
                    print(response.json().get('url'))
                    print(response.json().get('expire_date'))
                    print(response.status_code)
                    # return response()->json(['url' => $signedUrl]);
                    if response.status_code == 200:
                        url = response.json().get('url')
                        expire_date = response.json().get('expire_date')
                        if url:
                            record.url_shared = url
                            record.expire_date = expire_date
                        else:
                            record.url_shared = ''
                            raise UserError(_('Error al obtener el token: El servidor respondió sin un token válido. Verifica tus credenciales.'))
                    else:
                        record.url_shared = ''
                        raise UserError(_('Error al obtener el token: El servidor respondió con código %s. Verifica tus credenciales.') % response.status_code)
                except requests.exceptions.RequestException as e:
                    record.url_shared = ''
                    raise UserError(_('Error de conexión al obtener el token: No se pudo conectar a Philco Shop. Error: %s') % str(e))
                except UserError:
                    raise
                except Exception as e:
                    record.url_shared = ''
                    raise UserError(_('Error inesperado al obtener el token: %s') % str(e))


    def _validate_and_clean_url(self, url, field_label):
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https', 'ftp', 'ftps') or not parsed.netloc:
            raise UserError(_('El %s proporcionado no es válido. Por favor, ingresa un URL válido (ej: https://ejemplo.com).') % field_label)
        return url.rstrip('/')

    def _clean_url_vals(self, vals):
        url_fields = {
            'url_base': _('URL base'),
            'api_endpoint': _('endpoint de la API'),
        }
        for field, label in url_fields.items():
            if field in vals and vals[field]:
                vals[field] = self._validate_and_clean_url(vals[field], label)
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._clean_url_vals(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._clean_url_vals(vals)
        return super().write(vals)
    