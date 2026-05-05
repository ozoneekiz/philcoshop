import base64
import mimetypes
from pathlib import Path

from markupsafe import Markup

from odoo import models
from odoo.modules.module import get_module_resource


def _get_static_file_content(*path_parts):
    path = get_module_resource('philcoshop', *path_parts)
    if not path:
        path = Path(__file__).resolve().parents[1].joinpath(*path_parts)
    if not path or not Path(path).exists():
        return ''
    with open(path, 'rb') as static_file:
        return static_file.read()


def _get_shipping_label_css():
    css = _get_static_file_content('static', 'src', 'css', 'shipping_label.css')
    return Markup(css.decode('utf-8')) if css else Markup('')


def _get_static_image_data_uri(filename):
    content = _get_static_file_content('static', 'src', 'img', filename)
    if not content:
        return ''
    mimetype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    encoded = base64.b64encode(content).decode('ascii')
    return 'data:%s;base64,%s' % (mimetype, encoded)


def _get_handling_icons():
    return {
        'fragil': _get_static_image_data_uri('fragil.svg'),
        'up': _get_static_image_data_uri('este_lado_arriba.svg'),
        'dry': _get_static_image_data_uri('no_mojar.svg'),
    }


def _get_package_labels(orders):
    labels = []
    for order in orders:
        package_total = max(int(order.package_count or 1), 1)
        for package_index in range(1, package_total + 1):
            labels.append({
                'order': order,
                'package_index': package_index,
                'package_total': package_total,
            })
    return labels


class ShippingLabelA6Report(models.AbstractModel):
    _name = 'report.philcoshop.shipping_label_a6'
    _description = 'Reporte Etiquetas de Envio A6'

    def _get_report_values(self, docids, data=None):
        orders = self.env['sale.order'].browse(docids)
        labels = _get_package_labels(orders)
        return {
            'doc_ids': docids,
            'doc_model': 'sale.order',
            'orders': orders,
            'labels': labels,
            'handling_icons': _get_handling_icons(),
            'label_css': _get_shipping_label_css(),
        }


class ShippingLabelA4Report(models.AbstractModel):
    _name = 'report.philcoshop.shipping_label_a4'
    _description = 'Reporte Etiquetas de Envio A4'

    def _get_report_values(self, docids, data=None):
        orders = self.env['sale.order'].browse(docids)
        labels = _get_package_labels(orders)
        chunks = [labels[index:index + 4] for index in range(0, len(labels), 4)]
        if chunks and len(chunks[-1]) < 4:
            chunks[-1] += [False] * (4 - len(chunks[-1]))

        return {
            'doc_ids': docids,
            'doc_model': 'sale.order',
            'chunks': chunks,
            'handling_icons': _get_handling_icons(),
            'label_css': _get_shipping_label_css(),
        }
