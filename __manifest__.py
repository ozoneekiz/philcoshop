{
    "name": "TiendasPhilco Conect",
    "version": "18.0.1.0.0",
    "category": "Philco Addons",
    "summary": "Extiende el modelo de producto de Odoo para integrar con tiendasphilco",
    "description": """
        Este módulo mejora el modelo de producto de Odoo agregando campos relacionados tiendas philco.

        Key Features:
        - Agrega campos para almacenar el estado de listado d(Activo, Borrador, Pendiente).
        - Almacena el precio y la disponibilidad de stock para tienda web.
        - Proporciona un campo para la URL del porductopara un acceso rápido.
        - Se integra perfectamente con el sistema de gestión de productos existente de Odoo.
        
    """,
    "author": "Pedro Herrera",
    "depends": ["product"],
    "data": [
        "security/ir.model.access.csv",
        "views/product_view.xml",
        "views/web_order_view.xml",
        "views/conexion_view.xml",
        "views/menu_view.xml",
    ],
      
    


    'license': 'AGPL-3',
    'installable': True,
    'auto_install': False,
    'application': True,
}
