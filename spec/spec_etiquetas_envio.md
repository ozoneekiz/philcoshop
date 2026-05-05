# SPEC: Módulo de Impresión de Etiquetas de Envío
**Proyecto:** Addon Odoo 18 — Etiquetas de envío para `sale.order`  
**Versión:** 1.0  
**Estado:** Listo para desarrollo

---

## 1. Contexto

El módulo extiende el addon existente de sincronización Odoo ↔ Laravel. El campo `transport_company_name` ya existe en `sale.order`. Se necesita imprimir etiquetas de envío en formato A6 horizontal para una o más órdenes seleccionadas desde la vista lista, o desde el formulario individual.

---

## 2. Alcance

| Incluido | Excluido |
|---|---|
| Etiqueta A6 horizontal con datos del cliente | Integración con API de courier |
| Botón en vista lista (action en `action_buttons`) | Tracking / seguimiento de envíos |
| Botón en formulario individual | Cálculo de costos de envío |
| Vista previa antes de imprimir | |
| Reporte QWeb (PDF) | |
| **Modo A4: 4 etiquetas por hoja (2×2 grid)** | |
| **Modo A6: 1 etiqueta por página** | |

---

## 3. Estructura del Addon

El módulo se agrega **dentro del addon existente** (no es un addon separado). Los archivos nuevos o modificados son:

```
<tu_addon>/
├── __manifest__.py                       ← agregar nuevas dependencias y vistas
├── models/
│   └── sale_order.py                     ← ya existe, agregar método de acción
├── report/
│   ├── shipping_label_report.py          ← NUEVO: clase del reporte (compartida)
│   ├── shipping_label_a6_template.xml    ← NUEVO: plantilla QWeb modo A6 (1 por página)
│   └── shipping_label_a4_template.xml    ← NUEVO: plantilla QWeb modo A4 (2×2 por hoja)
└── views/
    └── sale_order_views.xml              ← NUEVO o existente: botones en tree y form
```

---

## 4. Campos de Datos

### 4.1 Fuente de datos por campo en la etiqueta

| Campo en etiqueta | Modelo | Campo Odoo |
|---|---|---|
| Nombre del cliente | `res.partner` | `partner_id.name` |
| Tipo de documento | `res.partner` | `partner_id.l10n_latam_identification_type_id.name` |
| Número de documento | `res.partner` | `partner_id.vat` |
| Dirección completa | `res.partner` | `partner_id.street`, `partner_id.city`, `partner_id.state_id.name` |
| Agencia / Transportista | `sale.order` | `transport_company_name` |

### 4.2 Formato de la dirección

Concatenar en este orden, omitiendo los que estén vacíos:
```
{street}, {city}, {state_id.name}
```

---

## 5. Diseño de la Etiqueta

**Tamaño:** A6 horizontal → 148mm × 105mm  
**Orientación:** Landscape  
**Márgenes:** 8mm en todos los lados  
**Fuente:** Sans-serif (preferencia: Arial o similar disponible en wkhtmltopdf)

### 5.1 Layout de la etiqueta (wireframe)

```
┌──────────────────────────────────────────────────────┐
│  AGENCIA:  [transport_company_name]                   │
│  ─────────────────────────────────────────────────   │
│                                                       │
│  DESTINATARIO                                         │
│  Nombre:    [partner_id.name]                         │
│  Documento: [tipo] [número]                           │
│  Dirección: [street], [city], [state]                 │
│                                                       │
│  ─────────────────────────────────────────────────   │
│  Pedido N°: [sale.order.name]         (pequeño pie)   │
└──────────────────────────────────────────────────────┘
```

**Notas de diseño:**
- La agencia va en la parte superior con fuente más grande y resaltada (bold, ~14pt).
- El bloque "DESTINATARIO" usa etiquetas en negrita y valores en normal (~11pt).
- El número de pedido va al pie en gris claro (~8pt) solo como referencia interna.
- Si se imprimen múltiples órdenes, cada etiqueta ocupa una página A6 independiente.

---

## 6. Comportamiento del Flujo

### 6.1 Desde la vista lista (`tree`) de `sale.order`

1. El usuario selecciona una o más órdenes usando los checkboxes.
2. Aparecen **dos botones** en la barra de acciones superior:
   - **"Etiquetas A4"** → genera PDF en A4 con hasta 4 etiquetas por hoja en grid 2×2.
   - **"Etiquetas A6"** → genera PDF con 1 etiqueta por página en tamaño A6 horizontal.
3. Al hacer clic en cualquiera, Odoo abre directamente la vista previa del PDF en una nueva pestaña.
4. Desde la vista previa el usuario usa el botón **"Imprimir"** del navegador o de Odoo.

### 6.2 Desde el formulario individual de `sale.order`

1. Se agregan **dos botones** en la barra superior del formulario:
   - **"Etiqueta A4"**
   - **"Etiqueta A6"**
2. Al hacer clic genera el PDF correspondiente de esa única orden.
3. Mismo comportamiento de previsualización que en el punto anterior.

### 6.3 Lógica de paginación modo A4 (2×2 grid)

- Las órdenes se agrupan en grupos de 4.
- Cada grupo ocupa una hoja A4.
- Si el total de órdenes no es múltiplo de 4, la última hoja tendrá las celdas sobrantes vacías (con borde visible para corte).
- Ejemplo: 6 órdenes → 2 hojas A4. Hoja 1: órdenes 1-4. Hoja 2: órdenes 5-6 + 2 celdas vacías.

### 6.4 Validaciones antes de imprimir

Antes de generar el PDF, verificar que cada orden tenga:
- `partner_id` asignado.
- `transport_company_name` no vacío.

Si alguna validación falla, mostrar un `UserError` descriptivo indicando qué orden y qué campo falta. No bloquear las demás órdenes válidas si se seleccionan múltiples.

---

## 7. Implementación Técnica

### 7.1 `__manifest__.py`

Agregar en `data`:
```python
'report/shipping_label_a6_template.xml',
'report/shipping_label_a4_template.xml',
'views/sale_order_views.xml',
```

### 7.2 `report/shipping_label_report.py`

Una sola clase AbstractModel compartida por ambos reportes. El modo A4 agrupa las órdenes en chunks de 4 para el grid:

```python
from odoo import models

class ShippingLabelReport(models.AbstractModel):
    _name = 'report.nombre_addon.shipping_label_a6'
    _description = 'Reporte Etiquetas de Envío A6'

    def _get_report_values(self, docids, data=None):
        orders = self.env['sale.order'].browse(docids)
        return {
            'orders': orders,
            'doc_ids': docids,
            'doc_model': 'sale.order',
        }


class ShippingLabelA4Report(models.AbstractModel):
    _name = 'report.nombre_addon.shipping_label_a4'
    _description = 'Reporte Etiquetas de Envío A4 (2x2)'

    def _get_report_values(self, docids, data=None):
        orders = self.env['sale.order'].browse(docids)
        # Agrupar en chunks de 4 para el grid 2x2
        orders_list = list(orders)
        chunks = [orders_list[i:i+4] for i in range(0, len(orders_list), 4)]
        # Rellenar el último chunk con None si tiene menos de 4
        if chunks and len(chunks[-1]) < 4:
            chunks[-1] += [None] * (4 - len(chunks[-1]))
        return {
            'chunks': chunks,
            'doc_ids': docids,
            'doc_model': 'sale.order',
        }
```

> ⚠️ Reemplazar `nombre_addon` con el nombre técnico real del addon.

### 7.3 `report/shipping_label_a6_template.xml` (modo A6, 1 por página)

```xml
<odoo>
  <report
    id="action_shipping_label_a6_report"
    model="sale.order"
    string="Etiqueta de Envío (A6)"
    report_type="qweb-pdf"
    name="nombre_addon.shipping_label_a6"
    file="nombre_addon.shipping_label_a6"
    paperformat="paperformat_shipping_label_a6"
  />

  <!-- Formato A6 horizontal -->
  <record id="paperformat_shipping_label_a6" model="report.paperformat">
    <field name="name">A6 Horizontal - Etiqueta Envío</field>
    <field name="default" eval="False"/>
    <field name="format">custom</field>
    <field name="page_height">105</field>
    <field name="page_width">148</field>
    <field name="orientation">Landscape</field>
    <field name="margin_top">8</field>
    <field name="margin_bottom">8</field>
    <field name="margin_left">8</field>
    <field name="margin_right">8</field>
    <field name="header_line" eval="False"/>
    <field name="header_spacing">0</field>
    <field name="dpi">96</field>
  </record>

  <template id="shipping_label_a6">
    <t t-call="web.html_container">
      <t t-foreach="orders" t-as="order">
        <div class="page">
          <div style="font-family: Arial, sans-serif; height: 100%;">
            <!-- Agencia -->
            <div style="border-bottom: 2px solid #333; padding-bottom: 6px; margin-bottom: 10px;">
              <span style="font-size: 8pt; color: #555;">AGENCIA:</span><br/>
              <strong style="font-size: 14pt;">
                <t t-esc="order.transport_company_name or '—'"/>
              </strong>
            </div>
            <!-- Destinatario -->
            <div style="margin-bottom: 10px;">
              <p style="font-size: 8pt; color: #555; margin: 0 0 4px 0;">DESTINATARIO</p>
              <table style="font-size: 11pt; width: 100%; border-collapse: collapse;">
                <tr>
                  <td style="font-weight: bold; width: 90px; vertical-align: top;">Nombre:</td>
                  <td><t t-esc="order.partner_id.name"/></td>
                </tr>
                <tr>
                  <td style="font-weight: bold; vertical-align: top;">Documento:</td>
                  <td>
                    <t t-esc="order.partner_id.l10n_latam_identification_type_id.name or ''"/>
                    <t t-esc="' ' + (order.partner_id.vat or '')"/>
                  </td>
                </tr>
                <tr>
                  <td style="font-weight: bold; vertical-align: top;">Dirección:</td>
                  <td>
                    <t t-esc="', '.join(filter(None, [
                      order.partner_id.street,
                      order.partner_id.city,
                      order.partner_id.state_id.name if order.partner_id.state_id else None
                    ]))"/>
                  </td>
                </tr>
              </table>
            </div>
            <!-- Pie -->
            <div style="border-top: 1px solid #ccc; padding-top: 4px; margin-top: auto;">
              <span style="font-size: 8pt; color: #aaa;">
                Pedido N°: <t t-esc="order.name"/>
              </span>
            </div>
          </div>
        </div>
      </t>
    </t>
  </template>
</odoo>
```

### 7.4 `report/shipping_label_a4_template.xml` (modo A4, grid 2×2)

```xml
<odoo>
  <report
    id="action_shipping_label_a4_report"
    model="sale.order"
    string="Etiqueta de Envío (A4 - 4 por hoja)"
    report_type="qweb-pdf"
    name="nombre_addon.shipping_label_a4"
    file="nombre_addon.shipping_label_a4"
    paperformat="paperformat_a4_default"
  />

  <!--
    Se usa el paperformat A4 estándar de Odoo (portrait, márgenes mínimos).
    Si no existe 'paperformat_a4_default' en tu instancia, referencia
    el paper format por defecto de Odoo: ref="base.paperformat_euro"
  -->

  <template id="shipping_label_a4">
    <t t-call="web.html_container">
      <!-- chunks = lista de listas de 4 órdenes (o None para celdas vacías) -->
      <t t-foreach="chunks" t-as="chunk">
        <div class="page">
          <!--
            Grid 2x2 en A4 portrait (210mm × 297mm).
            Cada celda = aprox. 105mm × 148mm (A6 horizontal).
            Usamos una tabla HTML de 2 columnas.
          -->
          <table style="
            width: 100%;
            height: 100%;
            border-collapse: collapse;
            table-layout: fixed;
          ">
            <tr style="height: 50%;">
              <!-- Celda 1 (posición 0) -->
              <td style="width: 50%; border: 1px dashed #aaa; padding: 8px; vertical-align: top;">
                <t t-if="chunk[0]">
                  <t t-call="nombre_addon.shipping_label_a4_cell">
                    <t t-set="order" t-value="chunk[0]"/>
                  </t>
                </t>
              </td>
              <!-- Celda 2 (posición 1) -->
              <td style="width: 50%; border: 1px dashed #aaa; padding: 8px; vertical-align: top;">
                <t t-if="chunk[1]">
                  <t t-call="nombre_addon.shipping_label_a4_cell">
                    <t t-set="order" t-value="chunk[1]"/>
                  </t>
                </t>
              </td>
            </tr>
            <tr style="height: 50%;">
              <!-- Celda 3 (posición 2) -->
              <td style="width: 50%; border: 1px dashed #aaa; padding: 8px; vertical-align: top;">
                <t t-if="chunk[2]">
                  <t t-call="nombre_addon.shipping_label_a4_cell">
                    <t t-set="order" t-value="chunk[2]"/>
                  </t>
                </t>
              </td>
              <!-- Celda 4 (posición 3) -->
              <td style="width: 50%; border: 1px dashed #aaa; padding: 8px; vertical-align: top;">
                <t t-if="chunk[3]">
                  <t t-call="nombre_addon.shipping_label_a4_cell">
                    <t t-set="order" t-value="chunk[3]"/>
                  </t>
                </t>
              </td>
            </tr>
          </table>
        </div>
      </t>
    </t>
  </template>

  <!-- Sub-template reutilizable: contenido de una celda individual -->
  <template id="shipping_label_a4_cell">
    <div style="font-family: Arial, sans-serif; height: 100%;">
      <!-- Agencia -->
      <div style="border-bottom: 2px solid #333; padding-bottom: 4px; margin-bottom: 8px;">
        <span style="font-size: 7pt; color: #555;">AGENCIA:</span><br/>
        <strong style="font-size: 12pt;">
          <t t-esc="order.transport_company_name or '—'"/>
        </strong>
      </div>
      <!-- Destinatario -->
      <div style="margin-bottom: 8px;">
        <p style="font-size: 7pt; color: #555; margin: 0 0 3px 0;">DESTINATARIO</p>
        <table style="font-size: 10pt; width: 100%; border-collapse: collapse;">
          <tr>
            <td style="font-weight: bold; width: 80px; vertical-align: top;">Nombre:</td>
            <td><t t-esc="order.partner_id.name"/></td>
          </tr>
          <tr>
            <td style="font-weight: bold; vertical-align: top;">Documento:</td>
            <td>
              <t t-esc="order.partner_id.l10n_latam_identification_type_id.name or ''"/>
              <t t-esc="' ' + (order.partner_id.vat or '')"/>
            </td>
          </tr>
          <tr>
            <td style="font-weight: bold; vertical-align: top;">Dirección:</td>
            <td>
              <t t-esc="', '.join(filter(None, [
                order.partner_id.street,
                order.partner_id.city,
                order.partner_id.state_id.name if order.partner_id.state_id else None
              ]))"/>
            </td>
          </tr>
        </table>
      </div>
      <!-- Pie -->
      <div style="border-top: 1px solid #ccc; padding-top: 3px;">
        <span style="font-size: 7pt; color: #aaa;">
          Pedido N°: <t t-esc="order.name"/>
        </span>
      </div>
    </div>
  </template>
</odoo>
```

> ℹ️ El borde `dashed` en cada celda sirve como guía de corte. Si no quieres línea visible, cámbialo a `border: none`.

### 7.5 Acciones del servidor — `views/sale_order_views.xml`

Dos `ir.actions.server`, una por modo:

```xml
<!-- Acción: Etiquetas A6 -->
<record id="action_print_shipping_label_a6" model="ir.actions.server">
  <field name="name">Etiquetas de Envío (A6)</field>
  <field name="model_id" ref="sale.model_sale_order"/>
  <field name="binding_model_id" ref="sale.model_sale_order"/>
  <field name="binding_view_types">list,form</field>
  <field name="state">code</field>
  <field name="code">
action = env.ref('nombre_addon.action_shipping_label_a6_report').report_action(records)
  </field>
</record>

<!-- Acción: Etiquetas A4 (4 por hoja) -->
<record id="action_print_shipping_label_a4" model="ir.actions.server">
  <field name="name">Etiquetas de Envío (A4 - 4 por hoja)</field>
  <field name="model_id" ref="sale.model_sale_order"/>
  <field name="binding_model_id" ref="sale.model_sale_order"/>
  <field name="binding_view_types">list,form</field>
  <field name="state">code</field>
  <field name="code">
action = env.ref('nombre_addon.action_shipping_label_a4_report').report_action(records)
  </field>
</record>
```

### 7.6 Botones explícitos en formulario — `views/sale_order_views.xml`

```xml
<record id="view_sale_order_form_shipping_buttons" model="ir.ui.view">
  <field name="name">sale.order.form.shipping.buttons</field>
  <field name="model">sale.order</field>
  <field name="inherit_id" ref="sale.view_order_form"/>
  <field name="arch" type="xml">
    <xpath expr="//div[hasclass('o_statusbar_buttons')]" position="inside">
      <button name="%(nombre_addon.action_print_shipping_label_a6)d"
              string="Etiqueta A6"
              type="action"
              class="btn-secondary"
              icon="fa-tag"/>
      <button name="%(nombre_addon.action_print_shipping_label_a4)d"
              string="Etiquetas A4"
              type="action"
              class="btn-secondary"
              icon="fa-tags"/>
    </xpath>
  </field>
</record>
```

---

## 8. Mejoras Recomendadas

Las siguientes mejoras son opcionales pero agregan valor sin complejidad excesiva:

**8.1 Manejo de dirección vacía**  
Si `street`, `city` y `state` están todos vacíos, mostrar el texto `"Sin dirección registrada"` en rojo en la etiqueta para alertar visualmente antes de imprimir.

**8.2 Indicador visual en la lista**  
Agregar un decorador en la vista lista que resalte en rojo/naranja las órdenes que tengan `transport_company_name` vacío, para identificar fácilmente cuáles no están listas para imprimir.

```xml
<list decoration-warning="not transport_company_name">
```

**8.3 Número de copia**  
Opcionalmente, pasar en `data` un parámetro `copies` para que el reporte genere N copias de cada etiqueta (útil para etiquetas físicas donde se necesita duplicado).

**8.4 Soporte para partner de entrega**  
Considerar usar `partner_shipping_id` en lugar de `partner_id` para los datos del destinatario, ya que en Odoo puede ser diferente a la empresa facturadora. Confirmar con el usuario si aplica a su flujo.

---

## 9. Checklist de Desarrollo

- [ ] Crear `report/shipping_label_report.py` con ambas clases AbstractModel
- [ ] Crear `report/shipping_label_a6_template.xml` con paperformat A6, `<report>` y template QWeb
- [ ] Crear `report/shipping_label_a4_template.xml` con `<report>`, template grid 2×2 y sub-template de celda
- [ ] Registrar ambos archivos en `__manifest__.py` (sección `data`)
- [ ] Agregar dos `ir.actions.server` con `binding_view_types="list,form"` en views XML
- [ ] Agregar dos botones explícitos en `<header>` del formulario via `xpath`
- [ ] Probar modo A6 con 1 orden
- [ ] Probar modo A6 con múltiples órdenes (cada una en su página)
- [ ] Probar modo A4 con 4 órdenes exactas (1 hoja completa)
- [ ] Probar modo A4 con 5 órdenes (2 hojas, última con 1 celda vacía)
- [ ] Probar modo A4 con 1 orden (1 hoja con 3 celdas vacías)
- [ ] Probar validación: orden sin `transport_company_name`
- [ ] Probar validación: orden sin `partner_id`
- [ ] Verificar que las 4 celdas en A4 queden alineadas y con igual tamaño
- [ ] Verificar que `l10n_latam_identification_type_id.name` muestre "DNI" o "RUC" correctamente

---

## 10. Notas Importantes

- En Odoo 18, `wkhtmltopdf` sigue siendo el motor de PDF por defecto. El tamaño custom en `report.paperformat` debe coincidir exactamente con las dimensiones A6 (148mm × 105mm).
- Si el addon ya tiene un archivo de vistas para `sale.order`, agregar los nuevos `<record>` al mismo archivo para evitar conflictos de herencia.
- El `inherit_id` del botón en el formulario (`sale.view_order_form`) puede variar si usas una vista personalizada existente — ajustar según corresponda.
- Sustituir **todas** las ocurrencias de `nombre_addon` por el nombre técnico real del módulo (el `name` en `__manifest__.py`).
