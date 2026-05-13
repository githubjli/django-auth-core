from decimal import Decimal

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.admin import KycProfileAdmin, MeowCreditRedeemRequestAdmin
from apps.accounts.constants import TOKEN_SYMBOL
from apps.accounts.models import KycDocument, KycProfile, MeowCreditLedger, MeowCreditPackage, MeowCreditRedeemRequest, MeowCreditWallet, PaymentOrder
from apps.accounts.services import MeowCreditService

User = get_user_model()


@override_settings(MEDIA_ROOT='/tmp/django-auth-core-test-media')
class KycAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='kyc@example.com', password='pass12345')
        self.client.force_authenticate(self.user)
        self.payload = {
            'full_name': 'Jenny Li',
            'date_of_birth': '1995-01-01',
            'nationality': 'CN',
            'id_type': KycProfile.ID_TYPE_PASSPORT,
            'id_number': 'E12345678',
            'id_expiry_date': '2030-01-01',
        }

    def test_get_me_without_profile_returns_not_submitted(self):
        response = self.client.get(reverse('kyc-me'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], KycProfile.STATUS_NOT_SUBMITTED)
        self.assertEqual(response.data['full_name'], '')
        self.assertIsNone(response.data['date_of_birth'])
        self.assertEqual(response.data['documents']['id_front'], None)
        self.assertEqual(response.data['documents']['selfie'], None)
        self.assertFalse(KycProfile.objects.filter(user=self.user).exists())

    def test_post_me_creates_pending_profile(self):
        response = self.client.post(reverse('kyc-me'), self.payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], KycProfile.STATUS_PENDING)
        self.assertEqual(response.data['full_name'], 'Jenny Li')
        profile = KycProfile.objects.get(user=self.user)
        self.assertEqual(profile.status, KycProfile.STATUS_PENDING)
        self.assertIsNotNone(profile.submitted_at)

    def test_patch_me_updates_profile(self):
        self.client.post(reverse('kyc-me'), self.payload, format='json')
        updated = {**self.payload, 'full_name': 'Jenny Wang', 'nationality': 'US'}

        response = self.client.patch(reverse('kyc-me'), updated, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['full_name'], 'Jenny Wang')
        self.assertEqual(response.data['nationality'], 'US')
        self.assertEqual(response.data['status'], KycProfile.STATUS_PENDING)

    def test_upload_id_front(self):
        response = self._upload_document(KycDocument.TYPE_ID_FRONT, 'front.jpg')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['document_type'], KycDocument.TYPE_ID_FRONT)
        self.assertIn('image_url', response.data)
        self.assertEqual(KycDocument.objects.filter(user=self.user, document_type=KycDocument.TYPE_ID_FRONT).count(), 1)

    def test_upload_selfie(self):
        response = self._upload_document(KycDocument.TYPE_SELFIE, 'selfie.jpg')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['document_type'], KycDocument.TYPE_SELFIE)
        self.assertEqual(KycDocument.objects.filter(user=self.user, document_type=KycDocument.TYPE_SELFIE).count(), 1)

    def test_submit_missing_images_returns_400(self):
        self.client.post(reverse('kyc-me'), self.payload, format='json')

        response = self.client.post(reverse('kyc-submit'), format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], 'id_front and selfie are required.')

    def test_submit_with_both_images_succeeds_pending(self):
        self.client.post(reverse('kyc-me'), self.payload, format='json')
        self._upload_document(KycDocument.TYPE_ID_FRONT, 'front.jpg')
        self._upload_document(KycDocument.TYPE_SELFIE, 'selfie.jpg')

        response = self.client.post(reverse('kyc-submit'), format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], KycProfile.STATUS_PENDING)
        self.assertIsNotNone(response.data['submitted_at'])
        self.assertIsNotNone(response.data['documents']['id_front'])
        self.assertIsNotNone(response.data['documents']['selfie'])

    def test_admin_action_approve_sets_status_approved(self):
        profile = KycProfile.objects.create(
            user=self.user,
            status=KycProfile.STATUS_PENDING,
            full_name='Jenny Li',
            date_of_birth='1995-01-01',
            nationality='CN',
            id_type=KycProfile.ID_TYPE_PASSPORT,
            id_number='E12345678',
            id_expiry_date='2030-01-01',
            submitted_at=timezone.now(),
        )
        admin_user = User.objects.create_superuser(email='admin@example.com', password='pass12345')
        request = RequestFactory().post('/admin/accounts/kycprofile/')
        request.user = admin_user
        model_admin = KycProfileAdmin(KycProfile, admin.site)
        model_admin.message_user = lambda *args, **kwargs: None

        model_admin.approve_selected_kyc(request, KycProfile.objects.filter(pk=profile.pk))

        profile.refresh_from_db()
        self.assertEqual(profile.status, KycProfile.STATUS_APPROVED)
        self.assertEqual(profile.reviewed_by, admin_user)
        self.assertIsNotNone(profile.reviewed_at)
        self.assertEqual(profile.reject_reason, '')

    def test_meow_credit_redeem_requires_kyc_approved(self):
        MeowCreditService.credit_recharge(user=self.user, amount=100, payment_order=self._payment_order(), target=self._package())

        response = self.client.post(
            reverse('meow-credit-redeem-list-create'),
            {'amount': 40, 'redeem_method': 'bank', 'account_snapshot': {'name': 'Cat'}},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('KYC approval is required before redeeming credits.', str(response.data))

    def test_meow_credit_redeem_succeeds_after_kyc_approved(self):
        KycProfile.objects.create(
            user=self.user,
            status=KycProfile.STATUS_APPROVED,
            full_name='Jenny Li',
            date_of_birth='1995-01-01',
            nationality='CN',
            id_type=KycProfile.ID_TYPE_PASSPORT,
            id_number='E12345678',
            id_expiry_date='2030-01-01',
        )
        MeowCreditService.credit_recharge(user=self.user, amount=100, payment_order=self._payment_order(), target=self._package())

        response = self.client.post(
            reverse('meow-credit-redeem-list-create'),
            {'amount': 40, 'redeem_method': 'bank', 'account_snapshot': {'name': 'Cat'}},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        wallet = MeowCreditWallet.objects.get(user=self.user)
        self.assertEqual(wallet.balance, 60)


    def test_admin_action_approve_redeem_requests_completes_pending_redeem(self):
        self._approved_kyc()
        MeowCreditService.credit_recharge(user=self.user, amount=100, payment_order=self._payment_order(), target=self._package())
        redeem = MeowCreditService.create_redeem_request(
            user=self.user,
            amount=40,
            redeem_method='bank',
            account_snapshot={'name': 'Cat'},
        )
        admin_user = User.objects.create_superuser(email='redeem-admin@example.com', password='pass12345')
        request = RequestFactory().post('/admin/accounts/meowcreditredeemrequest/')
        request.user = admin_user
        model_admin = MeowCreditRedeemRequestAdmin(MeowCreditRedeemRequest, admin.site)
        model_admin.message_user = lambda *args, **kwargs: None

        model_admin.approve_selected_redeem_requests(request, MeowCreditRedeemRequest.objects.filter(pk=redeem.pk))

        redeem.refresh_from_db()
        self.assertEqual(redeem.status, MeowCreditRedeemRequest.STATUS_COMPLETED)
        self.assertEqual(redeem.reviewed_by, admin_user)
        self.assertTrue(
            MeowCreditLedger.objects.filter(
                entry_type=MeowCreditLedger.TYPE_REDEEM,
                status=MeowCreditLedger.STATUS_COMPLETED,
                target_id=redeem.id,
            ).exists()
        )

    def test_admin_action_reject_redeem_requests_refunds_credits(self):
        self._approved_kyc()
        MeowCreditService.credit_recharge(user=self.user, amount=100, payment_order=self._payment_order(), target=self._package())
        redeem = MeowCreditService.create_redeem_request(
            user=self.user,
            amount=40,
            redeem_method='bank',
            account_snapshot={'name': 'Cat'},
        )
        wallet = MeowCreditWallet.objects.get(user=self.user)
        self.assertEqual(wallet.balance, 60)
        admin_user = User.objects.create_superuser(email='redeem-reject-admin@example.com', password='pass12345')
        request = RequestFactory().post('/admin/accounts/meowcreditredeemrequest/')
        request.user = admin_user
        model_admin = MeowCreditRedeemRequestAdmin(MeowCreditRedeemRequest, admin.site)
        model_admin.message_user = lambda *args, **kwargs: None

        model_admin.reject_selected_redeem_requests_and_refund(request, MeowCreditRedeemRequest.objects.filter(pk=redeem.pk))

        redeem.refresh_from_db()
        wallet.refresh_from_db()
        self.assertEqual(redeem.status, MeowCreditRedeemRequest.STATUS_REJECTED)
        self.assertEqual(redeem.reviewed_by, admin_user)
        self.assertEqual(redeem.reject_reason, 'Rejected by admin')
        self.assertEqual(wallet.balance, 100)
        self.assertTrue(
            MeowCreditLedger.objects.filter(
                entry_type=MeowCreditLedger.TYPE_REFUND,
                status=MeowCreditLedger.STATUS_COMPLETED,
                target_id=redeem.id,
            ).exists()
        )

    def _upload_document(self, document_type, filename):
        image = SimpleUploadedFile(filename, b'file-content', content_type='image/jpeg')
        return self.client.post(
            reverse('kyc-document-upload'),
            {'document_type': document_type, 'image': image},
            format='multipart',
        )


    def _approved_kyc(self):
        return KycProfile.objects.create(
            user=self.user,
            status=KycProfile.STATUS_APPROVED,
            full_name='Jenny Li',
            date_of_birth='1995-01-01',
            nationality='CN',
            id_type=KycProfile.ID_TYPE_PASSPORT,
            id_number='E12345678',
            id_expiry_date='2030-01-01',
        )

    def _package(self):
        return MeowCreditPackage.objects.create(
            code=f'kyc-package-{MeowCreditPackage.objects.count()}',
            name='KYC Package',
            credit_amount=100,
            price_amount=Decimal('50.00'),
            price_currency=TOKEN_SYMBOL,
        )

    def _payment_order(self):
        return PaymentOrder.objects.create(
            user=self.user,
            order_type=PaymentOrder.TYPE_MEOW_CREDITS_RECHARGE,
            target_type='kyc-test',
            order_no=f'KYC{PaymentOrder.objects.count()}',
            amount=Decimal('1.00'),
            expected_amount_lbc=Decimal('1.00'),
            currency=TOKEN_SYMBOL,
            status=PaymentOrder.STATUS_PAID,
        )
