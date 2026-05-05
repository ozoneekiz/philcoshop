# -*- coding: utf-8 -*-
import requests
import logging
from datetime import datetime
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AdvertisementVideo(models.TransientModel):
    """
    Modelo proxy para manejar advertisement_videos desde una API externa.
    Usa TransientModel para que Odoo cree la tabla _transient pero
    sobreescribimos todos los métodos CRUD para que operen contra la API.

    Los registros en la tabla transient son solo "fantasmas" temporales
    para que las vistas list/form de Odoo funcionen nativamente.
    """
    _name = 'advertisement.video'
    _description = 'Advertisement Videos (API Proxy)'
    _order = 'sort_order asc, id asc'
    _api_videos_endpoint = '/api/v1/advertisement-videos'

    # ─── Campos que mapean 1:1 con tu tabla ───────────────────────────────────
    external_id = fields.Integer(
        string='ID Externo',
        readonly=True,
        help='ID real en la base de datos externa'
    )
    name = fields.Char(
        string='Nombre',
        required=True
    )
    video_url = fields.Char(
        string='URL del Video',
        required=True
    )
    description = fields.Text(
        string='Descripción'
    )
    button_text = fields.Char(
        string='Texto del Botón'
    )
    button_url = fields.Char(
        string='URL del Botón'
    )
    is_active = fields.Boolean(
        string='Activo',
        default=True
    )
    sort_order = fields.Integer(
        string='Orden',
        default=0
    )
    starts_at = fields.Datetime(
        string='Fecha de Inicio'
    )
    ends_at = fields.Datetime(
        string='Fecha de Fin'
    )

    # ─── Estado visual del periodo ────────────────────────────────────────────
    status = fields.Selection(
        selection=[
            ('scheduled', 'Programado'),
            ('active', 'Activo'),
            ('expired', 'Expirado'),
            ('always', 'Sin fechas'),
        ],
        string='Estado',
        compute='_compute_status',
        store=False,
    )

    @api.depends('starts_at', 'ends_at', 'is_active')
    def _compute_status(self):
        now = datetime.now()
        for rec in self:
            if not rec.starts_at and not rec.ends_at:
                rec.status = 'always'
            elif rec.ends_at and rec.ends_at < now:
                rec.status = 'expired'
            elif rec.starts_at and rec.starts_at > now:
                rec.status = 'scheduled'
            else:
                rec.status = 'active'

    # ─── Helpers para obtener configuración de la API ─────────────────────────
    def _get_api_config(self):
        """Obtiene URL base y token desde la conexión activa de Philco Shop."""
        conexion = self.env['philco.conexion'].sudo().search([
            ('active', '=', True)
        ], limit=1, order='id desc')

        if not conexion:
            raise UserError(
                'No hay una conexión activa de Philco Shop. '
                'Configura una en el menú de Conexión.'
            )

        base_url = (conexion.api_endpoint or '').strip()
        api_key = (conexion.access_token or '').strip()
        _logger.debug('[ADV-VIDEO] _get_api_config: conexion=%s base_url=%s', conexion.name, base_url)

        if not base_url:
            raise UserError('La conexión activa no tiene API Endpoint configurado.')
        if not api_key:
            raise UserError('La conexión activa no tiene Access Token configurado.')

        return {
            'base_url': base_url.rstrip('/'),
            'headers': {
                'Authorization': f'Bearer {api_key}',
                'Accept': 'application/json',
                'Content-Type': 'application/json',
            }
        }

    def _api_request(self, method, endpoint, payload=None, raise_on_404=True):
        """Ejecuta una petición a la API y maneja errores de forma centralizada."""
        cfg = self._get_api_config()
        base_url = cfg['base_url'].rstrip('/')
        endpoint_path = f"/{endpoint.lstrip('/')}"

        # Evita /api/v1 duplicado si api_endpoint ya lo incluye.
        if base_url.endswith('/api/v1') and endpoint_path.startswith('/api/v1/'):
            endpoint_path = endpoint_path[len('/api/v1'):]

        url = f"{base_url}{endpoint_path}"

        _logger.info('[ADV-VIDEO] _api_request: %s %s', method, url)

        try:
            response = requests.request(
                method,
                url,
                json=payload,
                headers=cfg['headers'],
                timeout=15,
            )
            response.raise_for_status()
            result = response.json() if response.content else {}
            _logger.debug('[ADV-VIDEO] Respuesta %s %s: %s', method, url, result)
            return result

        except requests.exceptions.ConnectionError as e:
            _logger.error('[ADV-VIDEO] ConnectionError: %s - %s', url, str(e))
            raise UserError('No se pudo conectar con la API externa. Verifica la URL.')
        except requests.exceptions.Timeout:
            _logger.error('[ADV-VIDEO] Timeout: %s', url)
            raise UserError('La API tardó demasiado en responder (timeout 15s).')
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code
            _logger.error('[ADV-VIDEO] HTTPError [%s]: %s - %s', status, url, str(e))
            if status == 404 and not raise_on_404:
                return {'_not_found': True, 'status': 404}
            try:
                payload = e.response.json()
                msg = payload.get('message') if isinstance(payload, dict) else str(e)
            except Exception:
                msg = str(e)
            raise UserError(f'Error de API [{status}]: {msg}')

    @staticmethod
    def _extract_api_records(response):
        """Normaliza distintas respuestas del API a una lista de registros."""
        if isinstance(response, list):
            return response
        if isinstance(response, dict):
            records = response.get('data', response)
            if isinstance(records, list):
                return records
            if isinstance(records, dict):
                return [records]
        return []

    # ─── Conversión entre formato API ↔ formato Odoo ─────────────────────────
    @staticmethod
    def _api_to_odoo(data: dict) -> dict:
        """Convierte un registro de la API a valores de campo de Odoo."""
        def parse_dt(val):
            if not val:
                return False
            # Laravel/MySQL devuelve "2024-01-15T10:00:00.000000Z" o "2024-01-15 10:00:00"
            for fmt in ('%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%d %H:%M:%S'):
                try:
                    return datetime.strptime(val, fmt)
                except ValueError:
                    continue
            return False

        def to_int(val, default=0):
            try:
                return int(val)
            except (TypeError, ValueError):
                return default

        def to_bool(val, default=True):
            if val is None:
                return default
            if isinstance(val, bool):
                return val
            if isinstance(val, str):
                return val.strip().lower() in ('1', 'true', 'yes', 'on')
            return bool(val)

        return {
            'external_id': data.get('id'),
            'name':        data.get('name', ''),
            'video_url':   data.get('video_url', ''),
            'description': data.get('description') or False,
            'button_text': data.get('button_text') or False,
            'button_url':  data.get('button_url') or False,
            'is_active':   to_bool(data.get('is_active', True), default=True),
            'sort_order':  to_int(data.get('sort_order', 0), default=0),
            'starts_at':   parse_dt(data.get('starts_at')),
            'ends_at':     parse_dt(data.get('ends_at')),
        }

    @staticmethod
    def _odoo_to_api(vals: dict) -> dict:
        """Convierte valores de campo de Odoo al formato que espera la API."""
        def fmt_dt(val):
            if not val:
                return None
            if isinstance(val, datetime):
                return val.strftime('%Y-%m-%d %H:%M:%S')
            return str(val)

        payload = {}
        field_map = {
            'name':        'name',
            'video_url':   'video_url',
            'description': 'description',
            'button_text': 'button_text',
            'button_url':  'button_url',
            'is_active':   'is_active',
            'sort_order':  'sort_order',
            'starts_at':   'starts_at',
            'ends_at':     'ends_at',
        }
        for odoo_field, api_field in field_map.items():
            if odoo_field in vals:
                value = vals[odoo_field]
                if odoo_field in ('starts_at', 'ends_at'):
                    payload[api_field] = fmt_dt(value)
                elif odoo_field == 'is_active':
                    payload[api_field] = 1 if value else 0
                else:
                    payload[api_field] = value if value is not False else None
        return payload

    # ─── CRUD: CREATE ─────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        """Crea el registro en la API externa, luego lo guarda en la tabla transient."""
        records = self.env['advertisement.video']
        for vals in vals_list:
            payload  = self._odoo_to_api(vals)
            response = self._api_request('POST', self._api_videos_endpoint, payload)

            # La API devuelve el registro creado; usamos su ID real
            created_data = response.get('data', response) if isinstance(response, dict) else response
            if isinstance(created_data, list):
                created_data = created_data[0] if created_data else {}
            external_id = (created_data or {}).get('id')
            if not external_id:
                raise UserError('La API no devolvió el ID del video creado.')
            vals['external_id'] = external_id
            records |= super(AdvertisementVideo, self).create(vals)

        return records

    # ─── CRUD: READ (carga desde la API en lugar de la BD de Odoo) ────────────
    @api.model
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None, count_limit=None, **kwargs):
        """
        Odoo 18 llama a web_search_read (no search_read) desde la vista lista.
        Sincronizamos con la API antes de dejar que el ORM lea la tabla transient.
        """
        self._sync_from_api()
        result = super().web_search_read(domain, specification, offset=offset, limit=limit,
                                         order=order, count_limit=count_limit, **kwargs)
        _logger.debug('[ADV-VIDEO] web_search_read retorna %s registros', len(result.get('records', [])))
        return result

    @api.model
    def search_read(self, domain=None, fields=None, offset=0, limit=None, order=None, **kwargs):
        """Mantenemos search_read por compatibilidad con llamadas directas."""
        self._sync_from_api()
        result = super().search_read(domain=domain or [], fields=fields,
                                     offset=offset, limit=limit, order=order, **kwargs)
        _logger.debug('[ADV-VIDEO] search_read retorna %s registros', len(result))
        return result

    def _sync_from_api(self):
        """
        Trae todos los registros de la API y actualiza la tabla transient.
        Estrategia: borrar todos los transient del usuario actual y recrearlos.
        """
        try:
            _logger.info('[ADV-VIDEO] _sync_from_api: iniciando...')
            response = self._api_request('GET', self._api_videos_endpoint)

            api_records = self._extract_api_records(response)

            _logger.info(f'[ADV-VIDEO] _sync_from_api: {len(api_records)} registros recibidos')

            # Limpiar solo registros transient locales (sin tocar la API externa).
            # NO usar existing.unlink() porque eso llama al unlink override y haria DELETE remoto.
            existing = self.sudo().search([])
            super(AdvertisementVideo, existing).unlink()

            # Recrear desde la API (usamos super() para evitar el loop)
            for item in api_records:
                odoo_vals = self._api_to_odoo(item)
                super(AdvertisementVideo, self).create(odoo_vals)

            _logger.info(f'[ADV-VIDEO] _sync_from_api: completado {len(api_records)} videos')
            
        except Exception as e:
            _logger.error(f'[ADV-VIDEO] Error en _sync_from_api: {str(e)}', exc_info=True)
            raise

    # ─── CRUD: WRITE (UPDATE) ─────────────────────────────────────────────────
    def write(self, vals):
        """Actualiza en la API primero, luego en local (transient)."""
        for record in self:
            if not record.external_id:
                raise UserError('Este registro no tiene ID externo. No se puede actualizar.')

            payload = self._odoo_to_api(vals)
            if payload:
                self._api_request(
                    'PUT',
                    f"{self._api_videos_endpoint}/{record.external_id}",
                    payload,
                )

        return super().write(vals)

    # ─── CRUD: DELETE ─────────────────────────────────────────────────────────
    def unlink(self):
        """Elimina en la API primero, luego borra el registro transient."""
        for record in self:
            if record.external_id:
                self._api_request(
                    'DELETE',
                    f"{self._api_videos_endpoint}/{record.external_id}",
                    raise_on_404=False,
                )
        return super().unlink()

    # ─── Acciones de botones en la vista ─────────────────────────────────────
    def action_toggle_active(self):
        """Activa o desactiva el video."""
        for record in self:
            record.write({'is_active': not record.is_active})
        return True

    def action_refresh(self):
        """Botón de refresco manual en la vista list."""
        self._sync_from_api()
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    @api.model
    def action_open_list(self):
        """Acción que abre la vista lista cargando desde la API."""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Videos Publicitarios',
            'res_model': 'advertisement.video',
            'view_mode': 'list,form',
            'target': 'current',
        }
