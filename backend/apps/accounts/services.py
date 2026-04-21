import base64
import json
import logging
import shutil
import subprocess
import tempfile
import secrets
from pathlib import Path
from urllib.parse import urlparse
from urllib import error, request as urllib_request
from uuid import uuid4
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import (
    ChainReceipt,
    LiveStream,
    MembershipPlan,
    OrderPayment,
    PaymentOrder,
    UserMembership,
    WalletAddress,
)

logger = logging.getLogger(__name__)


DEFAULT_THUMBNAIL_PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wn4n/4AAAAASUVORK5CYII='
)


class AntMediaLiveAdapter:
    STATUS_MAP = {
        'broadcasting': LiveStream.STATUS_LIVE,
        'finished': LiveStream.STATUS_ENDED,
    }

    def normalize_stream_fields(self, stream: LiveStream) -> dict:
        sync = self._fetch_broadcast_payload(stream.stream_key)
        payload = sync.get('payload')
        ant_status = payload.get('status') if payload else None
        mapped_status = self.STATUS_MAP.get(ant_status)

        django_status = stream.status
        effective_status = self._normalize_status(django_status, ant_status)
        status_source = 'ant_media' if ant_status is not None else 'django_control'

        return {
            'status': effective_status,
            'django_status': django_status,
            'effective_status': effective_status,
            'status_source': status_source,
            'raw_ant_media_status': ant_status,
            'rtmp_url': self._get_rtmp_url(),
            'playback_url': self._get_playback_url(stream.stream_key),
            'thumbnail_url': self._get_preview_image_url(stream.stream_key),
            'preview_image_url': self._get_preview_image_url(stream.stream_key),
            'snapshot_url': self._get_preview_image_url(stream.stream_key),
            'viewer_count': self._normalize_viewer_count(payload, fallback=stream.viewer_count),
            'sync_ok': sync.get('sync_ok', False),
            'sync_error': sync.get('sync_error'),
            'message': self._build_message(
                effective_status=effective_status,
                status_source=status_source,
                sync_ok=sync.get('sync_ok', False),
            ),
            'can_start': effective_status != LiveStream.STATUS_LIVE,
            'can_end': effective_status != LiveStream.STATUS_ENDED,
        }

    def get_browser_publish_config(self, stream: LiveStream) -> dict:
        stream_id = stream.stream_key
        websocket_url = self._get_websocket_url()
        adaptor_script_url = self._get_adaptor_script_url()
        app_name = settings.ANT_MEDIA_APP_NAME or None
        if not stream_id or not websocket_url or not adaptor_script_url:
            return {
                'ok': False,
                'error': 'ant_media_publish_config_unavailable',
                'message': 'Ant Media publish config is unavailable. Check backend Ant Media settings.',
            }
        return {
            'ok': True,
            'config': {
                'websocket_url': websocket_url,
                'adaptor_script_url': adaptor_script_url,
                'stream_id': stream_id,
                'app_name': app_name,
                'publish_mode': 'webrtc',
            },
        }

    def ensure_broadcast(self, stream: LiveStream) -> dict:
        if not settings.ANT_MEDIA_BASE_URL or not settings.ANT_MEDIA_REST_APP_NAME:
            return {
                'ok': False,
                'error': 'ant_media_not_configured',
                'message': 'Ant Media REST app is not configured.',
            }

        endpoint = (
            f"{settings.ANT_MEDIA_BASE_URL}/"
            f"{settings.ANT_MEDIA_REST_APP_NAME}/rest/v2/broadcasts/create"
        )
        payload = {
            'name': stream.title,
            'description': stream.description,
            'streamId': stream.stream_key,
            'type': 'liveStream',
        }
        body = json.dumps(payload).encode('utf-8')
        logger.debug('ant_media create_broadcast request url=%s payload=%s', endpoint, payload)
        request_obj = urllib_request.Request(
            endpoint,
            data=body,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        try:
            with urllib_request.urlopen(request_obj, timeout=3) as response:
                response_body = response.read().decode('utf-8')
                status_code = getattr(response, 'status', response.getcode())
        except (error.URLError, TimeoutError) as exc:
            logger.debug('ant_media create_broadcast failed url=%s error=%s', endpoint, exc)
            return {
                'ok': False,
                'error': 'ant_media_create_failed',
                'message': 'Unable to create broadcast on Ant Media.',
            }

        logger.debug(
            'ant_media create_broadcast response status=%s body=%s',
            status_code,
            response_body,
        )
        try:
            response_payload = json.loads(response_body)
        except (ValueError, json.JSONDecodeError):
            return {
                'ok': False,
                'error': 'invalid_ant_media_payload',
                'message': 'Invalid Ant Media create broadcast response.',
            }
        if not isinstance(response_payload, dict):
            return {
                'ok': False,
                'error': 'invalid_ant_media_payload',
                'message': 'Invalid Ant Media create broadcast response.',
            }
        stream_id = response_payload.get('streamId') or stream.stream_key
        return {'ok': True, 'stream_id': stream_id}

    def _normalize_status(self, db_status: str, ant_status: str | None) -> str:
        if ant_status is not None:
            if ant_status == 'broadcasting':
                return LiveStream.STATUS_LIVE
            if ant_status == 'finished':
                return LiveStream.STATUS_ENDED
            return 'waiting_for_signal'
        if db_status == LiveStream.STATUS_LIVE:
            return LiveStream.STATUS_LIVE
        if db_status == LiveStream.STATUS_ENDED:
            return LiveStream.STATUS_ENDED
        return 'ready'

    def _normalize_viewer_count(self, payload: dict | None, fallback: int) -> int:
        if not payload:
            return fallback
        keys = ('hlsViewerCount', 'webRTCViewerCount', 'rtmpViewerCount')
        total = 0
        has_metric = False
        for key in keys:
            value = payload.get(key)
            if value is None:
                continue
            try:
                total += int(value)
                has_metric = True
            except (TypeError, ValueError):
                continue
        return total if has_metric else fallback

    def _fetch_broadcast_payload(self, stream_key: str) -> dict:
        if not settings.ANT_MEDIA_SYNC_STATUS:
            return {'payload': None, 'sync_ok': False, 'sync_error': 'sync_disabled'}
        if not settings.ANT_MEDIA_BASE_URL or not settings.ANT_MEDIA_REST_APP_NAME:
            return {'payload': None, 'sync_ok': False, 'sync_error': 'ant_media_not_configured'}

        endpoint = (
            f"{settings.ANT_MEDIA_BASE_URL}/"
            f"{settings.ANT_MEDIA_REST_APP_NAME}/rest/v2/broadcasts/{stream_key}"
        )
        try:
            with urllib_request.urlopen(endpoint, timeout=2) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except (error.URLError, TimeoutError):
            return {'payload': None, 'sync_ok': False, 'sync_error': 'ant_media_unavailable'}
        except (ValueError, json.JSONDecodeError):
            return {'payload': None, 'sync_ok': False, 'sync_error': 'invalid_ant_media_payload'}
        if not isinstance(payload, dict):
            return {'payload': None, 'sync_ok': False, 'sync_error': 'invalid_ant_media_payload'}
        return {'payload': payload, 'sync_ok': True, 'sync_error': None}

    def _build_message(self, *, effective_status: str, status_source: str, sync_ok: bool) -> str:
        if status_source == 'ant_media' and effective_status == 'waiting_for_signal':
            return 'Ant Media session exists but is not yet broadcasting.'
        if not sync_ok:
            return 'Using Django control state because Ant Media status is unavailable.'
        if effective_status == LiveStream.STATUS_LIVE:
            return 'Stream is live.'
        if effective_status == LiveStream.STATUS_ENDED:
            return 'Stream has ended.'
        return 'Stream is ready to start.'

    def _get_rtmp_url(self) -> str | None:
        return settings.ANT_MEDIA_RTMP_BASE or None

    def _get_playback_url(self, stream_key: str) -> str | None:
        playback_base = settings.ANT_MEDIA_PLAYBACK_BASE
        if not playback_base and settings.ANT_MEDIA_BASE_URL:
            playback_base = f"{settings.ANT_MEDIA_BASE_URL}/{settings.ANT_MEDIA_APP_NAME}/streams"
        if not playback_base:
            return None
        return f"{playback_base}/{stream_key}.m3u8"

    def _get_preview_image_url(self, stream_key: str) -> str | None:
        if not settings.ANT_MEDIA_PREVIEW_BASE:
            return None
        return f"{settings.ANT_MEDIA_PREVIEW_BASE}/{stream_key}.png"

    def _get_websocket_url(self) -> str | None:
        explicit = getattr(settings, 'ANT_MEDIA_WEBSOCKET_URL', '')
        if explicit:
            return explicit.rstrip('/')
        base_url = settings.ANT_MEDIA_BASE_URL or ''
        app_name = settings.ANT_MEDIA_APP_NAME or ''
        if not base_url or not app_name:
            return None
        parsed = urlparse(base_url)
        if parsed.scheme not in {'http', 'https', 'ws', 'wss'} or not parsed.netloc:
            return None
        scheme = {'http': 'ws', 'https': 'wss'}.get(parsed.scheme, parsed.scheme)
        return f'{scheme}://{parsed.netloc}/{app_name}/websocket'

    def _get_adaptor_script_url(self) -> str | None:
        explicit = getattr(settings, 'ANT_MEDIA_ADAPTOR_SCRIPT_URL', '')
        if explicit:
            return explicit.rstrip('/')
        base_url = settings.ANT_MEDIA_BASE_URL or ''
        app_name = settings.ANT_MEDIA_APP_NAME or ''
        if not base_url or not app_name:
            return None
        return f'{base_url}/{app_name}/js/webrtc_adaptor.js'


class LbryDaemonError(RuntimeError):
    pass


class LbryDaemonConnectionError(LbryDaemonError):
    pass


class LbryDaemonRpcError(LbryDaemonError):
    pass


class LbryDaemonInvalidParamsError(LbryDaemonError):
    pass


class WalletAddressConflictError(LbryDaemonError):
    pass


class MembershipOrderPersistenceError(LbryDaemonError):
    pass


class LbryDaemonClient:
    def __init__(self, *, url: str | None = None, timeout: int | None = None):
        self.url = (url or settings.LBRY_DAEMON_URL or '').strip()
        self.timeout = int(timeout if timeout is not None else settings.LBRY_DAEMON_TIMEOUT)
        if not self.url:
            raise LbryDaemonError('LBRY daemon URL is not configured.')

    def wallet_list(self) -> list[dict]:
        result = self._rpc_call('wallet_list')
        if isinstance(result, list):
            return result
        raise LbryDaemonError('Unexpected wallet_list response from LBRY daemon.')

    def address_unused(self, wallet_id: str | None = None, account_id: str | None = None) -> dict:
        params: dict[str, str] = {}
        if wallet_id:
            params['wallet_id'] = str(wallet_id).strip()
        if account_id and str(account_id).strip():
            params['account_id'] = str(account_id).strip()
        logger.debug('lbry_daemon address_unused params=%s', params)
        result = self._rpc_call('address_unused', params)
        if isinstance(result, str):
            address = result.strip()
            if not address:
                raise LbryDaemonError('LBRY daemon did not return an unused address.')
            return {'address': address}
        if not isinstance(result, dict):
            raise LbryDaemonError('Unexpected address_unused response from LBRY daemon.')
        address = (result.get('address') or '').strip()
        if not address:
            raise LbryDaemonError('LBRY daemon did not return an unused address.')
        return result

    def transaction_list(
        self,
        wallet_id: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
    ) -> list[dict]:
        params: dict[str, int | str] = {}
        if wallet_id:
            params['wallet_id'] = wallet_id
        if page is not None:
            params['page'] = int(page)
        if page_size is not None:
            params['page_size'] = int(page_size)
        result = self._rpc_call('transaction_list', params)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            items = result.get('items')
            if isinstance(items, list):
                return items
        raise LbryDaemonError('Unexpected transaction_list response from LBRY daemon.')

    def transaction_show(self, txid: str) -> dict:
        result = self._rpc_call('transaction_show', {'txid': txid})
        if not isinstance(result, dict):
            raise LbryDaemonError('Unexpected transaction_show response from LBRY daemon.')
        return result

    def _rpc_call(self, method: str, params: dict | None = None):
        payload = {
            'jsonrpc': '2.0',
            'method': method,
            'params': params or {},
            'id': uuid4().hex,
        }
        body = json.dumps(payload).encode('utf-8')
        request_obj = urllib_request.Request(
            self.url,
            data=body,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        try:
            with urllib_request.urlopen(request_obj, timeout=self.timeout) as response:
                response_body = response.read().decode('utf-8')
        except (error.URLError, TimeoutError) as exc:
            raise LbryDaemonConnectionError(f'Failed to reach LBRY daemon: {exc}') from exc
        try:
            parsed = json.loads(response_body)
        except (ValueError, json.JSONDecodeError) as exc:
            raise LbryDaemonRpcError('Invalid JSON response from LBRY daemon.') from exc
        if not isinstance(parsed, dict):
            raise LbryDaemonRpcError('Invalid RPC envelope from LBRY daemon.')
        if parsed.get('error'):
            error_payload = parsed.get('error')
            if isinstance(error_payload, dict):
                message = str(error_payload.get('message') or error_payload)
                code = error_payload.get('code')
                if code in {-32602, 'INVALID_PARAMS'}:
                    raise LbryDaemonInvalidParamsError(f'LBRY daemon RPC invalid params: {message}')
            else:
                message = str(error_payload)
            raise LbryDaemonRpcError(f'LBRY daemon RPC error: {message}')
        return parsed.get('result')


class MembershipOrderService:
    daemon_client_class = LbryDaemonClient

    def __init__(self, *, daemon_client: LbryDaemonClient | None = None):
        self.daemon_client = daemon_client or self.daemon_client_class()

    @transaction.atomic
    def create_order(self, *, user, plan: MembershipPlan) -> PaymentOrder:
        order = None
        daemon_wallet_id = (settings.LBRY_PLATFORM_WALLET_ID or '').strip() or None
        daemon_account_id = (settings.LBRY_PLATFORM_ACCOUNT_ID or '').strip() or None
        try:
            order = PaymentOrder.objects.create(
                user=user,
                order_type=PaymentOrder.TYPE_MEMBERSHIP,
                target_type='membership_plan',
                target_id=plan.id,
                plan_code_snapshot=plan.code,
                plan_name_snapshot=plan.name,
                expected_amount_lbc=plan.price_lbc,
                status=PaymentOrder.STATUS_PENDING,
                order_no=self._generate_order_no(),
                expires_at=timezone.now() + timedelta(minutes=settings.MEMBERSHIP_ORDER_EXPIRE_MINUTES),
                amount='0.00',
                currency='LBC',
            )

            platform_receive_address = (settings.LBRY_PLATFORM_RECEIVE_ADDRESS or '').strip()
            logger.debug(
                'membership_order_create order_no=%s daemon_url=%s wallet_id=%s account_id_included=%s',
                order.order_no,
                getattr(self.daemon_client, 'url', ''),
                daemon_wallet_id,
                bool(daemon_account_id),
            )
            if platform_receive_address:
                address = platform_receive_address
                wallet_id = daemon_wallet_id or ''
                account_id = daemon_account_id or ''
                logger.debug('membership_order_create using_platform_receive_address=%s', address)
            else:
                request_params = {}
                if daemon_wallet_id:
                    request_params['wallet_id'] = daemon_wallet_id
                if daemon_account_id:
                    request_params['account_id'] = daemon_account_id
                logger.debug('membership_order_create address_unused_params=%s', request_params)

                daemon_result = self.daemon_client.address_unused(
                    wallet_id=daemon_wallet_id,
                    account_id=daemon_account_id,
                )
                address = (daemon_result.get('address') or '').strip()
                logger.debug('membership_order_create order_no=%s returned_address=%s', order.order_no, address)
                wallet_id = (daemon_result.get('wallet_id') or daemon_wallet_id or '').strip()
                account_id = (daemon_result.get('account_id') or daemon_account_id or '').strip()

                existing_assigned = WalletAddress.objects.filter(address=address, assigned_order__isnull=False).first()
                if existing_assigned is not None:
                    raise WalletAddressConflictError('Daemon returned an address already assigned to another order.')

            wallet_address, _ = WalletAddress.objects.update_or_create(
                address=address,
                defaults={
                    'label': f'membership:{order.order_no}',
                    'usage_type': WalletAddress.USAGE_MEMBERSHIP,
                    'status': WalletAddress.STATUS_ASSIGNED,
                    'assigned_order': order if not platform_receive_address else None,
                    'assigned_at': timezone.now() if not platform_receive_address else None,
                    'wallet_id': wallet_id,
                    'account_id': account_id,
                },
            )

            order.wallet_address = wallet_address
            order.pay_to_address = address
            order.save(update_fields=['wallet_address', 'pay_to_address', 'updated_at'])
            return order
        except (LbryDaemonConnectionError, LbryDaemonRpcError, LbryDaemonInvalidParamsError, WalletAddressConflictError) as exc:
            logger.exception(
                'membership_order_create failed category=%s order_no=%s rollback_expected=%s',
                exc.__class__.__name__,
                getattr(order, 'order_no', None),
                True,
            )
            raise
        except Exception as exc:
            logger.exception(
                'membership_order_create failed category=MembershipOrderPersistenceError order_no=%s rollback_expected=%s',
                getattr(order, 'order_no', None),
                True,
            )
            raise MembershipOrderPersistenceError('Failed to persist membership order/address assignment.') from exc

    def _generate_order_no(self) -> str:
        for _ in range(8):
            candidate = f'MO{timezone.now():%Y%m%d}{secrets.token_hex(4).upper()}'
            if not PaymentOrder.objects.filter(order_no=candidate).exists():
                return candidate
        raise LbryDaemonError('Unable to generate unique membership order number.')


class MembershipActivationService:
    @transaction.atomic
    def activate_for_order(self, *, order: PaymentOrder) -> UserMembership | None:
        if order.order_type != PaymentOrder.TYPE_MEMBERSHIP:
            return None
        if order.status not in {PaymentOrder.STATUS_PAID, PaymentOrder.STATUS_OVERPAID}:
            return None

        existing = UserMembership.objects.filter(source_order=order).select_related('plan').first()
        if existing is not None:
            return existing

        plan = MembershipPlan.objects.filter(pk=order.target_id).first()
        if plan is None:
            raise LbryDaemonError('Membership plan missing for paid membership order.')

        now = timezone.now()
        active_membership = UserMembership.objects.filter(
            user=order.user,
            status=UserMembership.STATUS_ACTIVE,
            ends_at__gt=now,
        ).order_by('-ends_at', '-id').first()

        starts_at = active_membership.ends_at if active_membership is not None else now
        ends_at = starts_at + timedelta(days=plan.duration_days)

        membership = UserMembership.objects.create(
            user=order.user,
            source_order=order,
            plan=plan,
            status=UserMembership.STATUS_ACTIVE,
            starts_at=starts_at,
            ends_at=ends_at,
        )
        return membership


class PaymentDetectionService:
    daemon_client_class = LbryDaemonClient

    def __init__(self, *, daemon_client: LbryDaemonClient | None = None):
        self.daemon_client = daemon_client or self.daemon_client_class()
        self.min_confirmations = int(settings.LBC_MIN_CONFIRMATIONS)
        self.page_size = int(settings.LBC_TX_PAGE_SIZE)

    @transaction.atomic
    def sync_membership_orders(self) -> dict:
        orders = list(
            PaymentOrder.objects.select_related('wallet_address').filter(
                order_type=PaymentOrder.TYPE_MEMBERSHIP,
                status__in=[
                    PaymentOrder.STATUS_PENDING,
                    PaymentOrder.STATUS_EXPIRED,
                    PaymentOrder.STATUS_UNDERPAID,
                ],
            ).exclude(pay_to_address='')
        )
        if not orders:
            return {'scanned_orders': 0, 'matched_receipts': 0, 'paid_orders': 0, 'activated_memberships': 0}

        orders_by_address: dict[str, list[PaymentOrder]] = {}
        for order in orders:
            orders_by_address.setdefault(order.pay_to_address, []).append(order)
        for key in orders_by_address:
            orders_by_address[key] = sorted(orders_by_address[key], key=lambda item: (item.created_at, item.id))
        wallet_ids = {order.wallet_address.wallet_id for order in orders if order.wallet_address and order.wallet_address.wallet_id}
        if not wallet_ids:
            if settings.LBRY_PLATFORM_WALLET_ID:
                wallet_ids = {settings.LBRY_PLATFORM_WALLET_ID}
            else:
                wallet_ids = {''}

        txids: set[str] = set()
        for wallet_id in wallet_ids:
            tx_summaries = self.daemon_client.transaction_list(
                wallet_id=wallet_id or None,
                page=1,
                page_size=self.page_size,
            )
            for tx in tx_summaries:
                txid = (tx.get('txid') or tx.get('id') or '').strip()
                if txid:
                    txids.add(txid)

        matched_receipts = 0
        paid_orders: set[int] = set()
        activation_service = MembershipActivationService()
        activated = 0

        for txid in txids:
            tx_detail = self.daemon_client.transaction_show(txid)
            outputs = self._extract_outputs(tx_detail)
            confirmations = self._extract_confirmations(tx_detail)
            block_height = tx_detail.get('height') or tx_detail.get('block_height')
            wallet_id = (tx_detail.get('wallet_id') or '').strip()
            for output in outputs:
                address = (output.get('address') or '').strip()
                candidate_orders = orders_by_address.get(address, [])
                if not candidate_orders:
                    continue
                amount = self._to_decimal(output.get('amount') or output.get('amount_lbc'))
                if amount is None:
                    continue
                order = self._select_candidate_order(candidate_orders=candidate_orders, txid=txid, amount=amount)
                if order is None:
                    continue
                vout = output.get('nout')
                if vout is None:
                    vout = output.get('vout')
                receipt = self._upsert_receipt(
                    txid=txid,
                    vout=vout,
                    address=address,
                    amount=amount,
                    confirmations=confirmations,
                    block_height=block_height,
                    raw_payload=tx_detail,
                    matched_order=order,
                    wallet_id=wallet_id or (order.wallet_address.wallet_id if order.wallet_address else ''),
                )
                self._upsert_order_payment(order=order, receipt=receipt, txid=txid, amount=amount, confirmations=confirmations)
                matched_receipts += 1
                if self._apply_payment_state(order=order, amount=amount, confirmations=confirmations, txid=txid):
                    paid_orders.add(order.id)
                    membership = activation_service.activate_for_order(order=order)
                    if membership is not None:
                        activated += 1

        return {
            'scanned_orders': len(orders),
            'matched_receipts': matched_receipts,
            'paid_orders': len(paid_orders),
            'activated_memberships': activated,
        }

    def _select_candidate_order(
        self,
        *,
        candidate_orders: list[PaymentOrder],
        txid: str,
        amount: Decimal,
    ) -> PaymentOrder | None:
        hinted = next(
            (
                item for item in candidate_orders
                if item.txid == txid and item.status in {PaymentOrder.STATUS_PENDING, PaymentOrder.STATUS_EXPIRED, PaymentOrder.STATUS_UNDERPAID}
            ),
            None,
        )
        if hinted is not None:
            return hinted

        for item in candidate_orders:
            if item.status in {PaymentOrder.STATUS_PENDING, PaymentOrder.STATUS_EXPIRED, PaymentOrder.STATUS_UNDERPAID} and amount >= (item.expected_amount_lbc or Decimal('0')):
                return item
        for item in candidate_orders:
            if item.status in {PaymentOrder.STATUS_PENDING, PaymentOrder.STATUS_EXPIRED, PaymentOrder.STATUS_UNDERPAID}:
                return item
        return None

    def _extract_outputs(self, tx_detail: dict) -> list[dict]:
        outputs = tx_detail.get('outputs')
        if isinstance(outputs, list):
            parsed_outputs = []
            for index, output in enumerate(outputs):
                if not isinstance(output, dict):
                    continue
                address = output.get('address')
                if not address:
                    addresses = output.get('addresses')
                    if isinstance(addresses, list) and addresses:
                        address = addresses[0]
                parsed_outputs.append(
                    {
                        'address': address,
                        'amount': output.get('amount'),
                        'vout': output.get('vout'),
                        'nout': output.get('nout', index),
                    }
                )
            return parsed_outputs
        return []

    def _extract_confirmations(self, tx_detail: dict) -> int:
        value = tx_detail.get('confirmations')
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    def _to_decimal(self, value) -> Decimal | None:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    def _upsert_receipt(
        self,
        *,
        txid: str,
        vout,
        address: str,
        amount: Decimal,
        confirmations: int,
        block_height,
        raw_payload: dict,
        matched_order: PaymentOrder,
        wallet_id: str,
    ) -> ChainReceipt:
        receipt, _ = ChainReceipt.objects.update_or_create(
            currency=ChainReceipt.CURRENCY_LBC,
            txid=txid,
            vout=vout,
            defaults={
                'wallet_id': wallet_id,
                'address': address,
                'amount_lbc': amount,
                'confirmations': confirmations,
                'block_height': block_height,
                'seen_at': timezone.now(),
                'confirmed_at': timezone.now() if confirmations >= self.min_confirmations else None,
                'raw_payload': raw_payload,
                'matched_order': matched_order,
                'match_status': ChainReceipt.MATCH_MATCHED,
            },
        )
        return receipt

    def _upsert_order_payment(
        self,
        *,
        order: PaymentOrder,
        receipt: ChainReceipt,
        txid: str,
        amount: Decimal,
        confirmations: int,
    ) -> OrderPayment:
        is_confirmed = confirmations >= self.min_confirmations and amount >= (order.expected_amount_lbc or Decimal('0'))
        payment_status = OrderPayment.PAYMENT_CONFIRMED if is_confirmed else OrderPayment.PAYMENT_PENDING
        order_payment, _ = OrderPayment.objects.update_or_create(
            order=order,
            receipt=receipt,
            defaults={
                'txid': txid,
                'amount_lbc': amount,
                'confirmations': confirmations,
                'payment_status': payment_status,
                'matched_at': timezone.now(),
            },
        )
        return order_payment

    def _apply_payment_state(self, *, order: PaymentOrder, amount: Decimal, confirmations: int, txid: str) -> bool:
        expected = order.expected_amount_lbc or Decimal('0')
        if amount < expected:
            if order.status != PaymentOrder.STATUS_UNDERPAID:
                order.status = PaymentOrder.STATUS_UNDERPAID
                order.actual_amount_lbc = amount
                order.txid = txid
                order.confirmations = confirmations
                order.save(update_fields=['status', 'actual_amount_lbc', 'txid', 'confirmations', 'updated_at'])
            return False
        if confirmations < self.min_confirmations:
            if order.actual_amount_lbc != amount or order.txid != txid or order.confirmations != confirmations:
                order.actual_amount_lbc = amount
                order.txid = txid
                order.confirmations = confirmations
                order.save(update_fields=['actual_amount_lbc', 'txid', 'confirmations', 'updated_at'])
            return False

        new_status = PaymentOrder.STATUS_PAID if amount == expected else PaymentOrder.STATUS_OVERPAID
        update_fields = ['status', 'actual_amount_lbc', 'txid', 'confirmations', 'paid_at', 'updated_at']
        if order.status == PaymentOrder.STATUS_EXPIRED:
            note = (order.paid_note or '').strip()
            note_suffix = 'paid_after_expiry'
            if note_suffix not in note:
                order.paid_note = f'{note};{note_suffix}'.strip(';')
                update_fields.append('paid_note')
        order.status = new_status
        order.actual_amount_lbc = amount
        order.txid = txid
        order.confirmations = confirmations
        if order.paid_at is None:
            order.paid_at = timezone.now()
        order.save(update_fields=update_fields)
        return True


def generate_video_thumbnail(video, time_offset: float = 1.0) -> bool:
    if not video.file:
        return False

    thumbnail_content = _extract_thumbnail_with_ffmpeg(video, time_offset=time_offset)
    if thumbnail_content is None:
        thumbnail_content = ContentFile(DEFAULT_THUMBNAIL_PNG)

    filename = f'video_{video.pk or "new"}_{uuid4().hex}.png'
    if video.thumbnail:
        video.thumbnail.delete(save=False)
    video.thumbnail.save(filename, thumbnail_content, save=False)
    return True


def _extract_thumbnail_with_ffmpeg(video, time_offset: float):
    ffmpeg_path = shutil.which('ffmpeg')
    if not ffmpeg_path:
        return None

    try:
        input_path = Path(video.file.path)
    except (NotImplementedError, ValueError):
        return None

    with tempfile.TemporaryDirectory() as temp_dir:
        output_path = Path(temp_dir) / 'thumbnail.png'
        for offset in (max(time_offset, 0), 0):
            completed = subprocess.run(
                [
                    ffmpeg_path,
                    '-y',
                    '-ss',
                    str(offset),
                    '-i',
                    str(input_path),
                    '-frames:v',
                    '1',
                    str(output_path),
                ],
                capture_output=True,
                text=True,
            )
            if completed.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                return ContentFile(output_path.read_bytes())

    return None
