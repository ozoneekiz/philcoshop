from odoo import models, fields

class PhilcoConexion(models.Model):
    _name = "philco.conexion"
    _description = "Conexion con Philco Shop"

    store_name = fields.Char(string="Nombre de la Tienda", required=True)
    url_base = fields.Char(string="URL de tienda", required=True)
    access_token = fields.Char(string="Token de api philco shop", required=True)
    active = fields.Boolean(string="Activo", default=True)

    
