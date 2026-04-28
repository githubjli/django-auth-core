import base64
import hashlib
import hmac
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
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.accounts.constants import BLOCKCHAIN_NAME, TOKEN_NAME, TOKEN_PEG, TOKEN_SYMBOL
from apps.accounts.models import (
    ChainReceipt,
    LiveStream,
    MembershipPlan,
    MeowPointLedger,
    MeowPointPackage,
    MeowPointPurchase,
    MeowPointWallet,
    OrderPayment,
    PaymentOrder,
    Product,
    ProductOrder,
    ProductShipment,
    ProductRefundRequest,
    SellerPayout,
    SellerPayoutAddress,
    UserMembership,
    UserShippingAddress,
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


class WalletPrototypeError(LbryDaemonError):
    pass


class WalletPrototypeValidationError(WalletPrototypeError):
    pass


def get_product_wallet_send_amount(payment_order: PaymentOrder, product_order: ProductOrder) -> Decimal:
    """
    Resolve the native-chain amount to send for product wallet prototype payments.

    Priority:
      1) payment_order.expected_amount_lbc (explicit settlement amount)
      2) payment_order.amount (legacy fallback for older rows)
    """
    treat_thb_ltt_as_native = bool(getattr(settings, 'PRODUCT_WALLET_PAYMENT_TREAT_THB_LTT_AS_NATIVE', True))
    product_currency = (product_order.currency or '').strip()

    if product_currency == TOKEN_SYMBOL and not treat_thb_ltt_as_native:
        raise WalletPrototypeValidationError(
            'Product wallet payment for THB-LTT is disabled by configuration.'
        )

    expected_amount = payment_order.expected_amount_lbc
    if expected_amount is not None and expected_amount > 0:
        return expected_amount

    if payment_order.amount and payment_order.amount > 0:
        return payment_order.amount

    raise WalletPrototypeValidationError('Product payment order is missing settlement amount.')


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

    def wallet_unlock(self, wallet_id: str, password: str):
        params = {'wallet_id': wallet_id, 'password': password}
        return self._rpc_call('wallet_unlock', params)

    def wallet_lock(self, wallet_id: str):
        return self._rpc_call('wallet_lock', {'wallet_id': wallet_id})

    def wallet_send(
        self,
        *,
        wallet_id: str,
        amount: str | Decimal,
        addresses: list[str],
        change_account_id: str | None = None,
        funding_account_ids: list[str] | None = None,
        blocking: bool = True,
    ):
        amount_value = format(amount, 'f') if isinstance(amount, Decimal) else str(amount)
        addresses_list = [str(address) for address in (addresses or [])]
        change_account_value = str(change_account_id) if change_account_id else None
        funding_account_list = [str(account_id) for account_id in funding_account_ids] if funding_account_ids else None
        blocking_value = bool(blocking)
        logger.debug(
            'lbry_daemon wallet_send_final_params wallet_id=%s amount=%s amount_type=%s addresses=%s addresses_type=%s '
            'address_item_types=%s change_account_id=%s change_account_id_type=%s funding_account_ids=%s funding_account_ids_type=%s '
            'funding_account_item_types=%s blocking=%s blocking_type=%s params_keys=%s',
            wallet_id,
            amount_value,
            type(amount_value).__name__,
            addresses_list,
            type(addresses_list).__name__,
            [type(item).__name__ for item in addresses_list],
            change_account_value,
            type(change_account_value).__name__ if change_account_value is not None else None,
            funding_account_list,
            type(funding_account_list).__name__ if funding_account_list is not None else None,
            [type(item).__name__ for item in funding_account_list] if funding_account_list is not None else None,
            blocking_value,
            type(blocking_value).__name__,
            ['wallet_id', 'amount', 'addresses', *(['change_account_id'] if change_account_value else []), *(['funding_account_ids'] if funding_account_list else []), 'blocking'],
        )
        params: dict[str, object] = {
            'wallet_id': wallet_id,
            'amount': amount_value,
            'addresses': addresses_list,
            'blocking': blocking_value,
        }
        if change_account_value:
            params['change_account_id'] = change_account_value
        if funding_account_list:
            params['funding_account_ids'] = funding_account_list
        return self._rpc_call('wallet_send', params)

    def account_balance(self, wallet_id: str, account_id: str | None = None):
        params: dict[str, str] = {'wallet_id': wallet_id}
        if account_id:
            params['account_id'] = account_id
        return self._rpc_call('account_balance', params)

    def _rpc_call(self, method: str, params: dict | None = None):
        payload = {
            'jsonrpc': '2.0',
            'method': method,
            'params': params or {},
            'id': uuid4().hex,
        }
        parsed_url = urlparse(self.url or '')
        params_payload = payload.get('params') if isinstance(payload.get('params'), dict) else {}
        logger.debug(
            'lbry_daemon rpc_envelope method=%s top_level_keys=%s params_keys=%s params_value_types=%s hostport=%s timeout=%s',
            method,
            sorted(payload.keys()),
            sorted(params_payload.keys()),
            {key: type(value).__name__ for key, value in params_payload.items()},
            parsed_url.netloc,
            self.timeout,
        )
        if method == 'wallet_send':
            logger.debug(
                'lbry_daemon rpc_wallet_send_envelope method=%s params_keys=%s params_value_types=%s daemon_hostport=%s timeout=%s',
                method,
                sorted(params_payload.keys()),
                {key: type(value).__name__ for key, value in params_payload.items()},
                parsed_url.netloc,
                self.timeout,
            )
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

    @transaction.atomic
    def verify_order_once(self, *, order: PaymentOrder, txid_hint: str | None = None) -> dict:
        if order.order_type != PaymentOrder.TYPE_MEMBERSHIP:
            return {'verified': False, 'message': 'unsupported_order_type'}

        txids: list[str] = []
        hinted = (txid_hint or '').strip()
        if hinted:
            txids.append(hinted)
        elif order.txid:
            txids.append(order.txid.strip())
        else:
            wallet_id = (
                (order.wallet_address.wallet_id if order.wallet_address else '')
                or settings.LBRY_PLATFORM_WALLET_ID
                or ''
            ).strip()
            tx_summaries = self.daemon_client.transaction_list(
                wallet_id=wallet_id or None,
                page=1,
                page_size=self.page_size,
            )
            txids.extend([(item.get('txid') or item.get('id') or '').strip() for item in tx_summaries if isinstance(item, dict)])

        activation_service = MembershipActivationService()
        matched = False
        for txid in [item for item in txids if item]:
            tx_detail = self.daemon_client.transaction_show(txid)
            outputs = self._extract_outputs(tx_detail)
            confirmations = self._extract_confirmations(tx_detail)
            block_height = tx_detail.get('height') or tx_detail.get('block_height')
            wallet_id = (tx_detail.get('wallet_id') or '').strip()
            for output in outputs:
                address = (output.get('address') or '').strip()
                if address != order.pay_to_address:
                    continue
                amount = self._to_decimal(output.get('amount') or output.get('amount_lbc'))
                if amount is None:
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
                matched = True
                paid = self._apply_payment_state(order=order, amount=amount, confirmations=confirmations, txid=txid)
                if paid:
                    activation_service.activate_for_order(order=order)
                order.refresh_from_db()
                return {
                    'verified': True,
                    'matched': True,
                    'paid': paid,
                    'status': order.status,
                    'confirmations': order.confirmations,
                    'txid': order.txid,
                }
        order.refresh_from_db()
        return {
            'verified': True,
            'matched': matched,
            'paid': order.status in {PaymentOrder.STATUS_PAID, PaymentOrder.STATUS_OVERPAID},
            'status': order.status,
            'confirmations': order.confirmations,
            'txid': order.txid,
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


def build_product_qr_signature_payload(
    *,
    version: int,
    payload_type: str,
    blockchain: str,
    token_symbol: str,
    order_no: str,
    pay_to_address: str,
    expected_amount: str,
    currency: str,
    expires_at: str,
) -> str:
    payload = {
        'version': version,
        'type': payload_type,
        'blockchain': blockchain,
        'token_symbol': token_symbol,
        'order_no': order_no,
        'pay_to_address': pay_to_address,
        'expected_amount': expected_amount,
        'currency': currency,
        'expires_at': expires_at,
    }
    return json.dumps(payload, separators=(',', ':'), sort_keys=True)


def sign_product_qr_payload(
    *,
    version: int,
    payload_type: str,
    order_no: str,
    pay_to_address: str,
    expected_amount: str,
    currency: str,
    expires_at: str,
) -> str:
    normalized_expected_amount = str(expected_amount).strip()
    try:
        normalized_expected_amount = format(Decimal(normalized_expected_amount).normalize(), 'f')
    except Exception:
        normalized_expected_amount = str(expected_amount)
    message = build_product_qr_signature_payload(
        version=version,
        payload_type=payload_type,
        blockchain=BLOCKCHAIN_NAME,
        token_symbol=TOKEN_SYMBOL,
        order_no=order_no,
        pay_to_address=pay_to_address,
        expected_amount=normalized_expected_amount,
        currency=currency,
        expires_at=expires_at,
    )
    secret = (settings.PAYMENT_QR_SIGNING_SECRET or settings.SECRET_KEY).encode('utf-8')
    return hmac.new(secret, message.encode('utf-8'), hashlib.sha256).hexdigest()


def verify_product_qr_signature(payload: dict) -> bool:
    expected_sig = sign_product_qr_payload(
        version=int(payload.get('version') or 0),
        payload_type=str(payload.get('type') or ''),
        order_no=str(payload.get('order_no') or ''),
        pay_to_address=str(payload.get('pay_to_address') or ''),
        expected_amount=str(payload.get('expected_amount') or ''),
        currency=str(payload.get('currency') or ''),
        expires_at=str(payload.get('expires_at') or ''),
    )
    provided_sig = str(payload.get('sig') or '')
    return bool(provided_sig) and hmac.compare_digest(provided_sig, expected_sig)


class ProductOrderService:
    daemon_client_class = LbryDaemonClient

    def __init__(self, *, daemon_client: LbryDaemonClient | None = None):
        self.daemon_client = daemon_client or self.daemon_client_class()

    def _resolve_receive_address(self) -> str:
        return (settings.PRODUCT_PLATFORM_RECEIVE_ADDRESS or settings.LBRY_PLATFORM_RECEIVE_ADDRESS or '').strip()

    def create_order(self, *, buyer, product, quantity: int, shipping_address: UserShippingAddress) -> ProductOrder:
        if quantity <= 0:
            raise ValueError('Quantity must be greater than zero.')
        if product.status != Product.STATUS_ACTIVE:
            raise ValueError('Product is not active.')
        if not product.store.is_active:
            raise ValueError('Seller store is not active.')
        if product.stock_quantity < quantity:
            raise ValueError('Insufficient product stock.')
        if shipping_address.user_id != buyer.id:
            raise ValueError('Shipping address does not belong to buyer.')
        receive_address = ''
        wallet_id = ''
        account_id = ''
        is_dynamic_address = False
        configured_receive_address = self._resolve_receive_address()
        if configured_receive_address:
            receive_address = configured_receive_address
            wallet_id = (settings.LBRY_PLATFORM_WALLET_ID or '').strip()
            account_id = (settings.LBRY_PLATFORM_ACCOUNT_ID or '').strip()
        else:
            daemon_wallet_id = (settings.LBRY_PLATFORM_WALLET_ID or '').strip() or None
            daemon_account_id = (settings.LBRY_PLATFORM_ACCOUNT_ID or '').strip() or None
            try:
                daemon_result = self.daemon_client.address_unused(
                    wallet_id=daemon_wallet_id,
                    account_id=daemon_account_id,
                )
            except LbryDaemonError as exc:
                raise RuntimeError('Unable to allocate product payment address from platform wallet.') from exc
            receive_address = (daemon_result.get('address') or '').strip()
            wallet_id = (daemon_result.get('wallet_id') or daemon_wallet_id or '').strip()
            account_id = (daemon_result.get('account_id') or daemon_account_id or '').strip()
            is_dynamic_address = True
        if not receive_address:
            raise RuntimeError('Unable to allocate product payment address from platform wallet.')

        with transaction.atomic():
            updated = Product.objects.filter(id=product.id, stock_quantity__gte=quantity).update(stock_quantity=F('stock_quantity') - quantity)
            if updated == 0:
                raise ValueError('Insufficient product stock.')
            product.refresh_from_db(fields=['stock_quantity'])
            order_no = self._generate_order_no()
            total_amount = (product.price_amount or Decimal('0')) * Decimal(quantity)
            now = timezone.now()
            expires_at = now + timedelta(minutes=int(settings.PRODUCT_ORDER_EXPIRE_MINUTES))
            payment_order = PaymentOrder.objects.create(
                user=buyer,
                product=product,
                order_type=PaymentOrder.TYPE_PRODUCT,
                target_type='product_order',
                amount=total_amount,
                expected_amount_lbc=total_amount,
                currency=TOKEN_SYMBOL,
                status=PaymentOrder.STATUS_PENDING,
                order_no=order_no,
                pay_to_address=receive_address,
                expires_at=expires_at,
            )
            if is_dynamic_address:
                existing_assigned = WalletAddress.objects.filter(
                    address=receive_address,
                    assigned_order__isnull=False,
                ).exclude(assigned_order=payment_order).first()
                if existing_assigned is not None:
                    raise RuntimeError('Unable to allocate product payment address from platform wallet.')
                wallet_address, _ = WalletAddress.objects.update_or_create(
                    address=receive_address,
                    defaults={
                        'label': f'product:{order_no}',
                        'usage_type': WalletAddress.USAGE_PRODUCT,
                        'status': WalletAddress.STATUS_ASSIGNED,
                        'assigned_order': payment_order,
                        'assigned_at': now,
                        'wallet_id': wallet_id,
                        'account_id': account_id,
                    },
                )
            else:
                wallet_address, _ = WalletAddress.objects.update_or_create(
                    address=receive_address,
                    defaults={
                        'label': f'product:{order_no}',
                        'usage_type': WalletAddress.USAGE_PRODUCT,
                        'status': WalletAddress.STATUS_AVAILABLE,
                        'assigned_order': None,
                        'assigned_at': None,
                        'wallet_id': wallet_id,
                        'account_id': account_id,
                    },
                )
            payment_order.wallet_address = wallet_address
            payment_order.save(update_fields=['wallet_address', 'updated_at'])
            product_order = ProductOrder.objects.create(
                order_no=order_no,
                buyer=buyer,
                seller_store=product.store,
                product=product,
                product_title_snapshot=product.title,
                product_price_snapshot=product.price_amount,
                quantity=quantity,
                total_amount=total_amount,
                currency=TOKEN_SYMBOL,
                status=ProductOrder.STATUS_PENDING_PAYMENT,
                shipping_address_snapshot=self._shipping_snapshot(shipping_address),
                payment_order=payment_order,
                stock_locked_at=now,
                expires_at=expires_at,
            )
            payment_order.target_id = product_order.id
            payment_order.save(update_fields=['target_id', 'updated_at'])
            return product_order

    def build_qr_payload(self, order: ProductOrder) -> dict:
        payment_order = order.payment_order
        expires_at_iso = payment_order.expires_at.isoformat() if payment_order and payment_order.expires_at else ''
        expected_amount = str(payment_order.expected_amount_lbc if payment_order and payment_order.expected_amount_lbc is not None else order.total_amount)
        signature = sign_product_qr_payload(
            version=1,
            payload_type='product_payment',
            order_no=order.order_no,
            pay_to_address=(payment_order.pay_to_address if payment_order else ''),
            expected_amount=expected_amount,
            currency=order.currency,
            expires_at=expires_at_iso,
        )
        return {
            'v': 1,
            't': 'product_payment',
            'o': order.order_no,
            's': signature,
        }

    def mark_paid(self, *, order: ProductOrder):
        now = timezone.now()
        with transaction.atomic():
            if order.status not in {ProductOrder.STATUS_PENDING_PAYMENT, ProductOrder.STATUS_CANCELLED}:
                raise ValueError('Only pending payment orders can be marked paid.')
            order.status = ProductOrder.STATUS_PAID
            order.paid_at = now
            order.cancelled_at = None
            order.cancel_reason = ''
            order.save(update_fields=['status', 'paid_at', 'cancelled_at', 'cancel_reason', 'updated_at'])
            if order.payment_order:
                order.payment_order.status = PaymentOrder.STATUS_PAID
                if order.payment_order.paid_at is None:
                    order.payment_order.paid_at = now
                order.payment_order.save(update_fields=['status', 'paid_at', 'updated_at'])

    def ship_order(self, *, order: ProductOrder, created_by, carrier: str, tracking_number: str, tracking_url: str = '', shipped_note: str = ''):
        if order.status != ProductOrder.STATUS_PAID:
            raise ValueError('Only paid orders can be shipped.')
        now = timezone.now()
        ProductShipment.objects.update_or_create(
            product_order=order,
            defaults={
                'carrier': carrier,
                'tracking_number': tracking_number,
                'tracking_url': tracking_url,
                'shipped_note': shipped_note,
                'created_by': created_by,
            },
        )
        order.status = ProductOrder.STATUS_SHIPPING
        order.shipped_at = now
        order.save(update_fields=['status', 'shipped_at', 'updated_at'])

    def confirm_received(self, *, order: ProductOrder):
        if order.status != ProductOrder.STATUS_SHIPPING:
            raise ValueError('Only shipping orders can be confirmed as received.')
        now = timezone.now()
        with transaction.atomic():
            order.status = ProductOrder.STATUS_COMPLETED
            order.completed_at = now
            order.save(update_fields=['status', 'completed_at', 'updated_at'])
            SellerPayout.objects.get_or_create(
                product_order=order,
                defaults={
                    'seller_store': order.seller_store,
                    'amount': order.total_amount,
                    'currency': order.currency,
                    'status': SellerPayout.STATUS_PENDING,
                },
            )

    def mark_settled(self, *, order: ProductOrder, txid: str, payout_address: str = '', note: str = ''):
        if order.status != ProductOrder.STATUS_COMPLETED:
            raise ValueError('Only completed orders can be settled.')
        has_active_refund = order.refund_requests.filter(
            status__in=[ProductRefundRequest.STATUS_REQUESTED, ProductRefundRequest.STATUS_APPROVED]
        ).exists()
        if has_active_refund:
            raise ValueError('Cannot settle order with active refund request.')
        now = timezone.now()
        with transaction.atomic():
            payout, _ = SellerPayout.objects.get_or_create(
                product_order=order,
                defaults={
                    'seller_store': order.seller_store,
                    'amount': order.total_amount,
                    'currency': order.currency,
                    'status': SellerPayout.STATUS_PENDING,
                },
            )
            payout.status = SellerPayout.STATUS_PAID
            payout.txid = txid
            payout.payout_address = payout_address
            payout.note = note
            payout.paid_at = now
            payout.failure_note = ''
            payout.save(update_fields=['status', 'txid', 'payout_address', 'note', 'paid_at', 'failure_note', 'updated_at'])
            order.status = ProductOrder.STATUS_SETTLED
            order.settled_at = now
            order.save(update_fields=['status', 'settled_at', 'updated_at'])

    @transaction.atomic
    def release_expired_pending_orders(self) -> dict:
        now = timezone.now()
        orders = list(
            ProductOrder.objects.select_related('payment_order', 'product').filter(
                status=ProductOrder.STATUS_PENDING_PAYMENT,
                expires_at__isnull=False,
                expires_at__lt=now,
                stock_released_at__isnull=True,
            )
        )
        released = 0
        restored_stock_quantity = 0
        for order in orders:
            self._release_stock_for_order(order=order, reason='payment_timeout')
            released += 1
            restored_stock_quantity += order.quantity
        return {
            'scanned_orders': len(orders),
            'released_orders': released,
            'restored_stock_quantity': restored_stock_quantity,
        }

    def _release_stock_for_order(self, *, order: ProductOrder, reason: str):
        now = timezone.now()
        if order.stock_released_at is not None:
            return
        Product.objects.filter(id=order.product_id).update(stock_quantity=F('stock_quantity') + order.quantity)
        order.status = ProductOrder.STATUS_CANCELLED
        order.cancel_reason = reason
        order.cancelled_at = now
        order.stock_released_at = now
        order.save(update_fields=['status', 'cancel_reason', 'cancelled_at', 'stock_released_at', 'updated_at'])
        if order.payment_order and order.payment_order.status in {
            PaymentOrder.STATUS_PENDING,
            PaymentOrder.STATUS_UNDERPAID,
            PaymentOrder.STATUS_EXPIRED,
        }:
            order.payment_order.status = PaymentOrder.STATUS_EXPIRED
            order.payment_order.save(update_fields=['status', 'updated_at'])

    def _shipping_snapshot(self, shipping_address: UserShippingAddress) -> dict:
        return {
            'receiver_name': shipping_address.receiver_name,
            'phone': shipping_address.phone,
            'country': shipping_address.country,
            'province': shipping_address.province,
            'city': shipping_address.city,
            'district': shipping_address.district,
            'street_address': shipping_address.street_address,
            'postal_code': shipping_address.postal_code,
        }

    def _generate_order_no(self) -> str:
        for _ in range(16):
            candidate = f'PO{timezone.now():%Y%m%d}{secrets.token_hex(4).upper()}'
            if not ProductOrder.objects.filter(order_no=candidate).exists():
                return candidate
        raise RuntimeError('Unable to generate unique product order number.')


class ProductPaymentDetectionService:
    daemon_client_class = LbryDaemonClient

    def __init__(self, *, daemon_client: LbryDaemonClient | None = None):
        self.daemon_client = daemon_client or self.daemon_client_class()
        self.min_confirmations = int(settings.LBC_MIN_CONFIRMATIONS)
        self.page_size = int(settings.LBC_TX_PAGE_SIZE)

    @transaction.atomic
    def sync_product_orders(self) -> dict:
        orders = list(
            PaymentOrder.objects.filter(
                order_type=PaymentOrder.TYPE_PRODUCT,
                target_type='product_order',
                status__in=[PaymentOrder.STATUS_PENDING, PaymentOrder.STATUS_UNDERPAID, PaymentOrder.STATUS_EXPIRED],
            ).exclude(pay_to_address='')
        )
        stats = {
            'scanned_orders': len(orders),
            'matched_receipts': 0,
            'paid_orders': 0,
            'underpaid_orders': 0,
            'overpaid_orders': 0,
            'errors': 0,
        }
        if not orders:
            return stats
        order_by_id = {order.id: order for order in orders}
        order_by_address: dict[str, list[PaymentOrder]] = {}
        for order in orders:
            order_by_address.setdefault(order.pay_to_address, []).append(order)
        txids: set[str] = set()
        for tx in self.daemon_client.transaction_list(page=1, page_size=self.page_size):
            txid = (tx.get('txid') or tx.get('id') or '').strip() if isinstance(tx, dict) else ''
            if txid:
                txids.add(txid)
        for txid in txids:
            try:
                tx_detail = self.daemon_client.transaction_show(txid)
            except LbryDaemonError:
                stats['errors'] += 1
                continue
            confirmations = self._extract_confirmations(tx_detail)
            block_height = tx_detail.get('height') or tx_detail.get('block_height')
            for output in self._extract_outputs(tx_detail):
                address = (output.get('address') or '').strip()
                candidate_orders = order_by_address.get(address) or []
                if not candidate_orders:
                    continue
                amount = self._to_decimal(output.get('amount') or output.get('amount_lbc'))
                if amount is None:
                    continue
                order = self._select_candidate_order(candidate_orders, txid=txid)
                if order is None:
                    continue
                vout = output.get('nout') if output.get('nout') is not None else output.get('vout')
                receipt = self._upsert_receipt(
                    txid=txid,
                    vout=vout,
                    address=address,
                    amount=amount,
                    confirmations=confirmations,
                    block_height=block_height,
                    raw_payload=tx_detail,
                    matched_order=order,
                )
                self._upsert_order_payment(order=order, receipt=receipt, txid=txid, amount=amount, confirmations=confirmations)
                stats['matched_receipts'] += 1
                outcome = self._apply_product_payment_state(order=order, amount=amount, confirmations=confirmations, txid=txid)
                if outcome == PaymentOrder.STATUS_PAID:
                    stats['paid_orders'] += 1
                elif outcome == PaymentOrder.STATUS_OVERPAID:
                    stats['overpaid_orders'] += 1
                elif outcome == PaymentOrder.STATUS_UNDERPAID:
                    stats['underpaid_orders'] += 1
                order_by_id[order.id] = order
        return stats

    @transaction.atomic
    def verify_product_order_once(self, *, order: PaymentOrder, txid_hint: str) -> dict:
        if order.order_type != PaymentOrder.TYPE_PRODUCT or order.target_type != 'product_order':
            return {'verified': False, 'message': 'unsupported_order_type'}
        txid = (txid_hint or '').strip()
        if not txid:
            return {'verified': False, 'message': 'txid_required'}
        try:
            tx_detail = self.daemon_client.transaction_show(txid)
        except LbryDaemonError:
            return {'verified': False, 'matched': False, 'paid': False, 'status': order.status, 'confirmations': order.confirmations, 'txid': order.txid}
        confirmations = self._extract_confirmations(tx_detail)
        block_height = tx_detail.get('height') or tx_detail.get('block_height')
        matched = False
        for output in self._extract_outputs(tx_detail):
            address = (output.get('address') or '').strip()
            if address != order.pay_to_address:
                continue
            amount = self._to_decimal(output.get('amount') or output.get('amount_lbc'))
            if amount is None:
                continue
            vout = output.get('nout') if output.get('nout') is not None else output.get('vout')
            receipt = self._upsert_receipt(
                txid=txid,
                vout=vout,
                address=address,
                amount=amount,
                confirmations=confirmations,
                block_height=block_height,
                raw_payload=tx_detail,
                matched_order=order,
            )
            self._upsert_order_payment(order=order, receipt=receipt, txid=txid, amount=amount, confirmations=confirmations)
            self._apply_product_payment_state(order=order, amount=amount, confirmations=confirmations, txid=txid)
            matched = True
            break
        order.refresh_from_db()
        product_order = ProductOrder.objects.filter(payment_order=order).first()
        return {
            'verified': True,
            'matched': matched,
            'paid': order.status in {PaymentOrder.STATUS_PAID, PaymentOrder.STATUS_OVERPAID},
            'status': order.status,
            'confirmations': order.confirmations,
            'txid': order.txid,
            'product_order_status': product_order.status if product_order else '',
        }

    def _select_candidate_order(self, candidate_orders: list[PaymentOrder], *, txid: str) -> PaymentOrder | None:
        for order in candidate_orders:
            if order.txid == txid and order.status in {PaymentOrder.STATUS_PENDING, PaymentOrder.STATUS_UNDERPAID, PaymentOrder.STATUS_EXPIRED}:
                return order
        for order in candidate_orders:
            if order.status in {PaymentOrder.STATUS_PENDING, PaymentOrder.STATUS_UNDERPAID, PaymentOrder.STATUS_EXPIRED}:
                return order
        return None

    def _apply_product_payment_state(self, *, order: PaymentOrder, amount: Decimal, confirmations: int, txid: str) -> str:
        expected = order.amount or Decimal('0')
        order.actual_amount_lbc = amount
        order.txid = txid
        order.confirmations = confirmations
        order_fields = ['actual_amount_lbc', 'txid', 'confirmations', 'updated_at']
        product_order = ProductOrder.objects.filter(payment_order=order).first()
        if amount < expected:
            order.status = PaymentOrder.STATUS_UNDERPAID
            order_fields.append('status')
            order.save(update_fields=order_fields)
            return order.status
        if confirmations < self.min_confirmations:
            order.save(update_fields=order_fields)
            return order.status
        order.status = PaymentOrder.STATUS_PAID if amount == expected else PaymentOrder.STATUS_OVERPAID
        order.paid_at = order.paid_at or timezone.now()
        order_fields.extend(['status', 'paid_at'])
        order.save(update_fields=order_fields)
        if product_order:
            product_order.status = ProductOrder.STATUS_PAID
            product_order.paid_at = product_order.paid_at or timezone.now()
            product_order.cancel_reason = ''
            product_order.cancelled_at = None
            product_order.save(update_fields=['status', 'paid_at', 'cancel_reason', 'cancelled_at', 'updated_at'])
        return order.status

    def _upsert_receipt(self, *, txid: str, vout, address: str, amount: Decimal, confirmations: int, block_height, raw_payload: dict, matched_order: PaymentOrder):
        receipt, _ = ChainReceipt.objects.update_or_create(
            currency=ChainReceipt.CURRENCY_LBC,
            txid=txid,
            vout=vout,
            defaults={
                'wallet_id': '',
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

    def _upsert_order_payment(self, *, order: PaymentOrder, receipt: ChainReceipt, txid: str, amount: Decimal, confirmations: int):
        is_confirmed = confirmations >= self.min_confirmations and amount >= (order.amount or Decimal('0'))
        payment_status = OrderPayment.PAYMENT_CONFIRMED if is_confirmed else OrderPayment.PAYMENT_PENDING
        OrderPayment.objects.update_or_create(
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

    def _extract_outputs(self, tx_detail: dict) -> list[dict]:
        outputs = tx_detail.get('outputs')
        if isinstance(outputs, list):
            parsed = []
            for idx, output in enumerate(outputs):
                if not isinstance(output, dict):
                    continue
                address = output.get('address') or ((output.get('addresses') or [None])[0])
                parsed.append({'address': address, 'amount': output.get('amount'), 'vout': output.get('vout'), 'nout': output.get('nout', idx)})
            return parsed
        return []

    def _extract_confirmations(self, tx_detail: dict) -> int:
        try:
            return max(0, int(tx_detail.get('confirmations') or 0))
        except (TypeError, ValueError):
            return 0

    def _to_decimal(self, value) -> Decimal | None:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None


class ProductPayoutService:
    daemon_client_class = LbryDaemonClient

    def __init__(self, *, daemon_client: LbryDaemonClient | None = None):
        self.daemon_client = daemon_client

    @transaction.atomic
    def settle_pending_payouts(self) -> dict:
        stats = {
            'scanned_payouts': 0,
            'eligible_payouts': 0,
            'settled_payouts': 0,
            'skipped_payouts': 0,
            'failed_payouts': 0,
        }
        if not settings.PRODUCT_AUTO_PAYOUT_ENABLED:
            return stats
        if self.daemon_client is None:
            self.daemon_client = self.daemon_client_class()
        threshold = timezone.now() - timedelta(hours=int(settings.PRODUCT_PAYOUT_MIN_DELAY_HOURS))
        payouts = list(
            SellerPayout.objects.select_related('product_order', 'seller_store').filter(
                status=SellerPayout.STATUS_PENDING,
                product_order__status=ProductOrder.STATUS_COMPLETED,
                product_order__completed_at__isnull=False,
                product_order__completed_at__lte=threshold,
            )
        )
        stats['scanned_payouts'] = len(payouts)
        for payout in payouts:
            order = payout.product_order
            has_active_refund = ProductRefundRequest.objects.filter(
                product_order=order,
                status__in=[ProductRefundRequest.STATUS_REQUESTED, ProductRefundRequest.STATUS_APPROVED],
            ).exists()
            if has_active_refund:
                stats['skipped_payouts'] += 1
                continue
            payout_address = self._resolve_payout_address(payout)
            if not payout_address:
                payout.failure_note = 'missing_default_payout_address'
                payout.save(update_fields=['failure_note', 'updated_at'])
                stats['skipped_payouts'] += 1
                continue
            wallet_id = (settings.PRODUCT_PAYOUT_WALLET_ID or settings.LBRY_PLATFORM_WALLET_ID or '').strip()
            if not wallet_id:
                payout.failure_note = 'missing_payout_wallet_id'
                payout.save(update_fields=['failure_note', 'updated_at'])
                stats['skipped_payouts'] += 1
                continue
            change_account_id = (settings.PRODUCT_PAYOUT_ACCOUNT_ID or settings.LBRY_PLATFORM_ACCOUNT_ID or '').strip() or None
            stats['eligible_payouts'] += 1
            try:
                result = self.daemon_client.wallet_send(
                    wallet_id=wallet_id,
                    amount=payout.amount,
                    addresses=[payout_address.address],
                    change_account_id=change_account_id,
                    funding_account_ids=[change_account_id] if change_account_id else None,
                    blocking=True,
                )
                txid = self._extract_txid(result)
            except LbryDaemonError:
                payout.status = SellerPayout.STATUS_FAILED
                payout.failure_note = 'wallet_send_failed'
                payout.save(update_fields=['status', 'failure_note', 'updated_at'])
                stats['failed_payouts'] += 1
                continue
            now = timezone.now()
            payout.status = SellerPayout.STATUS_PAID
            payout.txid = txid
            payout.payout_address = payout_address.address
            payout.paid_at = now
            payout.failure_note = ''
            payout.save(update_fields=['status', 'txid', 'payout_address', 'paid_at', 'failure_note', 'updated_at'])
            order.status = ProductOrder.STATUS_SETTLED
            order.settled_at = now
            order.save(update_fields=['status', 'settled_at', 'updated_at'])
            stats['settled_payouts'] += 1
        return stats

    def _resolve_payout_address(self, payout: SellerPayout) -> SellerPayoutAddress | None:
        address = SellerPayoutAddress.objects.filter(
            seller_store=payout.seller_store,
            is_active=True,
            is_default=True,
        ).order_by('-updated_at', '-id').first()
        return address

    def _extract_txid(self, payload) -> str:
        if isinstance(payload, str):
            return payload.strip()
        if isinstance(payload, dict):
            return str(payload.get('txid') or payload.get('id') or '').strip()
        return ''


class WalletPrototypePayOrderService:
    daemon_client_class = LbryDaemonClient

    def __init__(self, *, daemon_client: LbryDaemonClient | None = None):
        self.daemon_client = daemon_client or self.daemon_client_class()

    def pay_payment_order(self, *, user, order: PaymentOrder, wallet_id: str, password: str, amount_override: Decimal | None = None) -> dict:
        amount = amount_override if amount_override is not None else (order.expected_amount_lbc or order.amount or Decimal('0'))
        pay_to_address = (order.pay_to_address or '').strip()
        if amount <= 0 or not pay_to_address:
            raise WalletPrototypeValidationError('Order is missing payment amount/address.')

        product_order = None
        if order.order_type == PaymentOrder.TYPE_PRODUCT:
            try:
                product_order = order.linked_product_order
            except ProductOrder.DoesNotExist:
                product_order = None
        existing_txid = (order.txid or '').strip()
        if existing_txid:
            return {
                'order_no': order.order_no,
                'txid': existing_txid,
                'payment_order_status': order.status,
                'product_order_status': product_order.status if product_order else None,
                'confirmations': order.confirmations,
                'detail': 'Payment already submitted and is waiting for confirmation.',
                'wallet_relocked': False,
            }

        change_account_id = (user.primary_user_address or '').strip() or None
        funding_account_ids = [change_account_id] if change_account_id else None
        product_order = None
        if order.order_type == PaymentOrder.TYPE_PRODUCT:
            try:
                product_order = order.linked_product_order
            except ProductOrder.DoesNotExist:
                product_order = None
        unlock_ok = False
        send_ok = False
        lock_attempted = False
        lock_ok = False
        txid = ''
        send_result = None
        response_payload = None
        logger.info(
            'wallet_prototype_pay_order start order_no=%s user_id=%s wallet_id=%s pay_to_address=%s amount=%s',
            order.order_no,
            user.id,
            wallet_id,
            pay_to_address,
            amount,
        )
        try:
            unlock_result = self.daemon_client.wallet_unlock(wallet_id=wallet_id, password=password)
            logger.info(
                'wallet_prototype_pay_order unlock_result order_no=%s user_id=%s wallet_id=%s unlock_result_type=%s unlock_result_keys=%s',
                order.order_no,
                user.id,
                wallet_id,
                type(unlock_result).__name__,
                sorted(unlock_result.keys()) if isinstance(unlock_result, dict) else None,
            )
            if not self._is_wallet_unlock_success(unlock_result):
                raise LbryDaemonError('wallet_unlock did not return success.')
            unlock_ok = True
            daemon_url = self.daemon_client.url or ''
            parsed_url = urlparse(daemon_url) if daemon_url else None
            daemon_hostport = parsed_url.netloc if parsed_url else ''
            blocking_flag = True
            logger.debug(
                'wallet_prototype_pay_order wallet_send_params order_no=%s order_type=%s wallet_id=%s pay_to_address=%s daemon_amount=%s '
                'business_currency=%s expected_amount_lbc=%s payment_order_amount=%s payment_order_currency=%s '
                'funding_account_ids=%s change_account_id=%s blocking=%s daemon_hostport=%s daemon_timeout=%s',
                order.order_no,
                order.order_type,
                wallet_id,
                pay_to_address,
                amount,
                product_order.currency if product_order else order.currency,
                order.expected_amount_lbc,
                order.amount,
                order.currency,
                funding_account_ids,
                change_account_id,
                blocking_flag,
                daemon_hostport,
                self.daemon_client.timeout,
            )
            # TODO: downgrade/remove INFO diagnostics after wallet_send production debugging is complete.
            logger.debug(
                'wallet_prototype_pay_order before_wallet_send order_no=%s user_id=%s wallet_id=%s amount=%s amount_type=%s '
                'pay_to_address=%s pay_to_address_len=%s addresses=%s change_account_id=%s change_account_id_type=%s '
                'funding_account_ids=%s funding_account_ids_type=%s blocking=%s blocking_type=%s',
                order.order_no,
                user.id,
                wallet_id,
                amount,
                type(amount).__name__,
                pay_to_address,
                len(pay_to_address),
                [pay_to_address],
                change_account_id,
                type(change_account_id).__name__ if change_account_id is not None else None,
                funding_account_ids,
                type(funding_account_ids).__name__ if funding_account_ids is not None else None,
                blocking_flag,
                type(blocking_flag).__name__,
            )
            self._log_wallet_balance_diagnostics(
                wallet_id=wallet_id,
                change_account_id=change_account_id,
                funding_account_ids=funding_account_ids,
            )
            send_result = self.daemon_client.wallet_send(
                wallet_id=wallet_id,
                amount=amount,
                addresses=[pay_to_address],
                change_account_id=change_account_id,
                funding_account_ids=funding_account_ids,
                blocking=blocking_flag,
            )
            send_ok = True
            txid = self._extract_txid(send_result)
            if txid:
                order.txid = txid
                order.save(update_fields=['txid', 'updated_at'])
            response_payload = {
                'order_no': order.order_no,
                'txid': txid,
                'payment_order_status': order.status,
                'product_order_status': product_order.status if product_order else None,
                'confirmations': order.confirmations,
                'detail': 'Payment submitted. Waiting for on-chain confirmation.',
                'pay_to_address': pay_to_address,
                'expected_amount_lbc': str(amount),
                'status': order.status,
                'send_result': send_result if isinstance(send_result, dict) else {'raw': send_result},
                'warning': None,
            }
        except LbryDaemonError as exc:
            exc_message = str(exc)
            if 'Not enough funds' in exc_message:
                logger.warning(
                    'wallet_prototype_pay_order insufficient_funds order_no=%s user_id=%s wallet_id=%s required_amount=%s '
                    'amount_type=%s pay_to_address=%s pay_to_address_len=%s addresses=%s funding_account_ids=%s change_account_id=%s',
                    order.order_no,
                    user.id,
                    wallet_id,
                    amount,
                    type(amount).__name__,
                    pay_to_address,
                    len(pay_to_address),
                    [pay_to_address],
                    funding_account_ids,
                    change_account_id,
                )
                raise WalletPrototypeError(
                    'Buyer wallet does not have enough spendable funds for this transaction.'
                ) from exc
            logger.exception(
                'wallet_prototype_pay_order daemon_error order_no=%s user_id=%s wallet_id=%s unlock_ok=%s send_ok=%s',
                order.order_no,
                user.id,
                wallet_id,
                unlock_ok,
                send_ok,
            )
            raise WalletPrototypeError(f'Wallet prototype payment failed: {exc}') from exc
        finally:
            if unlock_ok:
                lock_attempted = True
                try:
                    self.daemon_client.wallet_lock(wallet_id=wallet_id)
                    lock_ok = True
                except LbryDaemonError:
                    logger.exception(
                        'wallet_prototype_pay_order lock_failed order_no=%s user_id=%s wallet_id=%s txid=%s',
                        order.order_no,
                        user.id,
                        wallet_id,
                        txid,
                    )
                    if send_ok and response_payload is not None:
                        response_payload['warning'] = 'wallet_lock_failed'
            logger.debug(
                'wallet_prototype_pay_order complete order_no=%s user_id=%s wallet_id=%s unlock_ok=%s send_ok=%s lock_attempted=%s lock_ok=%s txid=%s',
                order.order_no,
                user.id,
                wallet_id,
                unlock_ok,
                send_ok,
                lock_attempted,
                lock_ok,
                txid,
            )
        if send_ok and response_payload is not None:
            response_payload['wallet_relocked'] = lock_ok
            logger.info('wallet_prototype_pay_order success order_no=%s txid=%s', order.order_no, txid)
            return response_payload
        raise WalletPrototypeError('Wallet prototype payment failed.')

    def pay_order(self, *, user, order: PaymentOrder, wallet_id: str, password: str, amount_override: Decimal | None = None) -> dict:
        return self.pay_payment_order(
            user=user,
            order=order,
            wallet_id=wallet_id,
            password=password,
            amount_override=amount_override,
        )

    def _extract_txid(self, payload) -> str:
        if isinstance(payload, str):
            return payload.strip()
        if isinstance(payload, dict):
            return str(payload.get('txid') or payload.get('id') or '').strip()
        return ''

    def _is_wallet_unlock_success(self, unlock_result) -> bool:
        if unlock_result is True:
            return True
        if isinstance(unlock_result, dict):
            return unlock_result.get('result') is True
        return False

    def _log_wallet_balance_diagnostics(self, *, wallet_id: str, change_account_id: str | None, funding_account_ids: list[str] | None):
        target_account_id = change_account_id or (funding_account_ids[0] if funding_account_ids else None)
        try:
            balance_payload = self.daemon_client.account_balance(wallet_id=wallet_id, account_id=target_account_id)
        except LbryDaemonError as exc:
            logger.warning(
                'wallet_prototype_pay_order balance_diagnostics_failed wallet_id=%s account_id=%s error=%s',
                wallet_id,
                target_account_id,
                exc,
            )
            return
        balance_type = type(balance_payload).__name__
        balance_keys = sorted(balance_payload.keys()) if isinstance(balance_payload, dict) else None
        confirmed = balance_payload.get('confirmed') if isinstance(balance_payload, dict) else None
        available = balance_payload.get('available') if isinstance(balance_payload, dict) else None
        total = balance_payload.get('total') if isinstance(balance_payload, dict) else None
        logger.info(
            'wallet_prototype_pay_order balance_diagnostics wallet_id=%s account_id=%s payload_type=%s payload_keys=%s confirmed=%s available=%s total=%s',
            wallet_id,
            target_account_id,
            balance_type,
            balance_keys,
            confirmed,
            available,
            total,
        )


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


class MeowPointService:
    @staticmethod
    def get_or_create_wallet(user):
        wallet, _created = MeowPointWallet.objects.get_or_create(user=user)
        return wallet

    @staticmethod
    def add_points(
        *,
        user,
        amount: int,
        entry_type: str,
        target_type: str = '',
        target_id: int | None = None,
        payment_order: PaymentOrder | None = None,
        note: str = '',
        purchased_amount: int = 0,
        bonus_amount: int = 0,
    ):
        if amount <= 0:
            raise ValidationError('Amount must be greater than zero.')
        with transaction.atomic():
            wallet = MeowPointWallet.objects.select_for_update().get_or_create(user=user)[0]
            balance_before = wallet.balance
            balance_after = balance_before + amount

            wallet.balance = balance_after
            wallet.total_earned += amount
            wallet.total_purchased += max(int(purchased_amount), 0)
            wallet.total_bonus += max(int(bonus_amount), 0)
            wallet.save(update_fields=['balance', 'total_earned', 'total_purchased', 'total_bonus', 'updated_at'])

            ledger = MeowPointLedger.objects.create(
                user=user,
                entry_type=entry_type,
                amount=amount,
                balance_before=balance_before,
                balance_after=balance_after,
                target_type=target_type,
                target_id=target_id,
                payment_order=payment_order,
                note=note,
            )
        return wallet, ledger

    @staticmethod
    def spend_points(
        *,
        user,
        amount: int,
        entry_type: str = MeowPointLedger.TYPE_SPEND,
        target_type: str = '',
        target_id: int | None = None,
        payment_order: PaymentOrder | None = None,
        note: str = '',
    ):
        if amount <= 0:
            raise ValidationError('Amount must be greater than zero.')
        with transaction.atomic():
            wallet = MeowPointWallet.objects.select_for_update().get_or_create(user=user)[0]
            if wallet.balance < amount:
                raise ValidationError('Insufficient Meow Points balance.')

            balance_before = wallet.balance
            balance_after = balance_before - amount

            wallet.balance = balance_after
            wallet.total_spent += amount
            wallet.save(update_fields=['balance', 'total_spent', 'updated_at'])

            ledger = MeowPointLedger.objects.create(
                user=user,
                entry_type=entry_type,
                amount=-amount,
                balance_before=balance_before,
                balance_after=balance_after,
                target_type=target_type,
                target_id=target_id,
                payment_order=payment_order,
                note=note,
            )
        return wallet, ledger


class MeowPointPurchaseService:
    @transaction.atomic
    def create_order(self, *, user, package_code: str):
        package = MeowPointPackage.objects.filter(code=package_code, status=MeowPointPackage.STATUS_ACTIVE).first()
        if package is None:
            raise ValidationError({'package_code': ['Active Meow Points package not found.']})

        order_no = self._generate_order_no()
        purchase = MeowPointPurchase.objects.create(
            user=user,
            package=package,
            order_no=order_no,
            package_code_snapshot=package.code,
            package_name_snapshot=package.name,
            points_amount=package.points_amount,
            bonus_points=package.bonus_points,
            total_points=package.points_amount + package.bonus_points,
            price_amount=package.price_amount,
            price_currency=package.price_currency,
            status=MeowPointPurchase.STATUS_PENDING,
        )
        payment_order = PaymentOrder.objects.create(
            user=user,
            order_type=PaymentOrder.TYPE_MEOW_POINTS_RECHARGE,
            target_type='meow_point_purchase',
            target_id=purchase.id,
            order_no=order_no,
            amount=package.price_amount,
            currency=package.price_currency,
            status=PaymentOrder.STATUS_PENDING,
        )
        purchase.payment_order = payment_order
        purchase.save(update_fields=['payment_order', 'updated_at'])
        return purchase

    @transaction.atomic
    def credit_paid_purchase(self, purchase: MeowPointPurchase):
        locked_purchase = MeowPointPurchase.objects.select_for_update().select_related('payment_order').get(pk=purchase.pk)
        if locked_purchase.credited_at is not None:
            return locked_purchase

        payment_order = locked_purchase.payment_order
        if payment_order is None:
            raise ValidationError('Purchase does not have a linked payment order.')
        if payment_order.status not in {PaymentOrder.STATUS_PAID, PaymentOrder.STATUS_OVERPAID}:
            return locked_purchase

        wallet = MeowPointWallet.objects.select_for_update().get_or_create(user=locked_purchase.user)[0]
        balance_before = wallet.balance

        purchase_points = int(locked_purchase.points_amount)
        bonus_points = int(locked_purchase.bonus_points)
        total_points = purchase_points + bonus_points

        wallet.balance = balance_before + total_points
        wallet.total_earned += total_points
        wallet.total_purchased += purchase_points
        wallet.total_bonus += bonus_points
        wallet.save(update_fields=['balance', 'total_earned', 'total_purchased', 'total_bonus', 'updated_at'])

        MeowPointLedger.objects.create(
            user=locked_purchase.user,
            entry_type=MeowPointLedger.TYPE_PURCHASE,
            amount=purchase_points,
            balance_before=balance_before,
            balance_after=balance_before + purchase_points,
            target_type='meow_point_purchase',
            target_id=locked_purchase.id,
            payment_order=payment_order,
            note=f'Purchase credit for order {locked_purchase.order_no}',
        )
        if bonus_points > 0:
            MeowPointLedger.objects.create(
                user=locked_purchase.user,
                entry_type=MeowPointLedger.TYPE_BONUS,
                amount=bonus_points,
                balance_before=balance_before + purchase_points,
                balance_after=balance_before + total_points,
                target_type='meow_point_purchase',
                target_id=locked_purchase.id,
                payment_order=payment_order,
                note=f'Bonus credit for order {locked_purchase.order_no}',
            )

        paid_at = payment_order.paid_at or timezone.now()
        locked_purchase.status = MeowPointPurchase.STATUS_PAID
        locked_purchase.paid_at = paid_at
        locked_purchase.credited_at = timezone.now()
        locked_purchase.save(update_fields=['status', 'paid_at', 'credited_at', 'updated_at'])
        return locked_purchase

    def _generate_order_no(self):
        for _ in range(8):
            candidate = f'MP{timezone.now():%Y%m%d}{secrets.token_hex(4).upper()}'
            if not MeowPointPurchase.objects.filter(order_no=candidate).exists():
                return candidate
        raise ValidationError('Unable to generate unique Meow Points order number.')
