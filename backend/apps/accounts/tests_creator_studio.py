from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import DramaSeries, LiveStream, User, Video


class CreatorStudioAPITestCase(APITestCase):
    def setUp(self):
        self.creator = User.objects.create_user(email='creator-studio@example.com', password='pass1234', is_creator=True)
        self.other_creator = User.objects.create_user(email='other-creator@example.com', password='pass1234', is_creator=True)
        self.viewer = User.objects.create_user(email='viewer@example.com', password='pass1234', is_creator=False)

    def test_creator_video_list_is_paginated_and_scoped_to_current_creator(self):
        own_video = Video.objects.create(
            owner=self.creator,
            title='Own video',
            file=SimpleUploadedFile('own.mp4', b'own-video', content_type='video/mp4'),
        )
        Video.objects.create(
            owner=self.other_creator,
            title='Other video',
            file=SimpleUploadedFile('other.mp4', b'other-video', content_type='video/mp4'),
        )
        self.client.force_authenticate(self.creator)

        response = self.client.get(reverse('creator-video-list-create'), {'page': 1, 'page_size': 10})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(response.data.keys()), {'count', 'next', 'previous', 'results'})
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], own_video.id)

    def test_non_creator_cannot_use_creator_video_endpoint(self):
        self.client.force_authenticate(self.viewer)

        response = self.client.get(reverse('creator-video-list-create'))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_creator_can_upload_video_through_creator_endpoint(self):
        self.client.force_authenticate(self.creator)

        response = self.client.post(
            reverse('creator-video-list-create'),
            {
                'title': 'Creator upload',
                'file': SimpleUploadedFile('upload.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        video = Video.objects.get(pk=response.data['id'])
        self.assertEqual(video.owner_id, self.creator.id)

    def test_creator_live_stream_list_is_paginated_and_scoped_to_current_creator(self):
        own_stream = LiveStream.objects.create(owner=self.creator, title='Own live')
        LiveStream.objects.create(owner=self.other_creator, title='Other live')
        self.client.force_authenticate(self.creator)

        response = self.client.get(reverse('creator-live-stream-list'), {'page': 1, 'page_size': 10})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(response.data.keys()), {'count', 'next', 'previous', 'results'})
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], own_stream.id)

    def test_non_creator_cannot_use_creator_live_stream_endpoint(self):
        self.client.force_authenticate(self.viewer)

        response = self.client.get(reverse('creator-live-stream-list'))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_creator_drama_list_is_paginated(self):
        own_series = DramaSeries.objects.create(owner=self.creator, title='Own drama')
        DramaSeries.objects.create(owner=self.other_creator, title='Other drama')
        self.client.force_authenticate(self.creator)

        response = self.client.get(reverse('creator-drama-series-list-create'), {'page': 1, 'page_size': 10})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(response.data.keys()), {'count', 'next', 'previous', 'results'})
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], own_series.id)
