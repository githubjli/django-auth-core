from django.core.management.base import BaseCommand

from apps.accounts.models import DramaEpisode, DramaSeries


class Command(BaseCommand):
    help = 'Seed demo short-drama series and episodes (idempotent).'

    def handle(self, *args, **options):
        series_specs = [
            {
                'title': 'Bangkok Hearts',
                'description': 'A fast-paced city romance.',
                'tags': ['romance', 'urban'],
                'episodes': [
                    {'episode_no': 1, 'title': 'Episode 1', 'duration_seconds': 95, 'is_free': True},
                    {
                        'episode_no': 2,
                        'title': 'Episode 2',
                        'duration_seconds': 99,
                        'is_free': False,
                        'unlock_type': DramaEpisode.UNLOCK_MEOW_POINTS,
                        'meow_points_price': 30,
                    },
                    {
                        'episode_no': 3,
                        'title': 'Episode 3',
                        'duration_seconds': 102,
                        'is_free': False,
                        'unlock_type': DramaEpisode.UNLOCK_MEMBERSHIP,
                        'meow_points_price': 0,
                    },
                ],
            },
            {
                'title': 'Office Cat Boss',
                'description': 'Comedy drama with a mysterious feline CEO.',
                'tags': ['comedy', 'office'],
                'episodes': [
                    {'episode_no': 1, 'title': 'Episode 1', 'duration_seconds': 88, 'is_free': True},
                    {
                        'episode_no': 2,
                        'title': 'Episode 2',
                        'duration_seconds': 91,
                        'is_free': False,
                        'unlock_type': DramaEpisode.UNLOCK_AD_REWARD,
                        'meow_points_price': 0,
                    },
                ],
            },
        ]

        for spec in series_specs:
            episodes = spec.pop('episodes')
            series, _created = DramaSeries.objects.update_or_create(
                title=spec['title'],
                defaults={
                    'description': spec.get('description', ''),
                    'tags': spec.get('tags', []),
                    'status': DramaSeries.STATUS_PUBLISHED,
                    'is_active': True,
                },
            )

            for index, episode_spec in enumerate(episodes, start=1):
                is_free = episode_spec.get('is_free', False)
                unlock_type = episode_spec.get('unlock_type') or (
                    DramaEpisode.UNLOCK_FREE if is_free else DramaEpisode.UNLOCK_MEOW_POINTS
                )
                DramaEpisode.objects.update_or_create(
                    series=series,
                    episode_no=episode_spec['episode_no'],
                    defaults={
                        'title': episode_spec['title'],
                        'duration_seconds': episode_spec.get('duration_seconds', 0),
                        'is_free': is_free,
                        'unlock_type': unlock_type,
                        'meow_points_price': episode_spec.get('meow_points_price', 0),
                        'sort_order': index,
                        'is_active': True,
                    },
                )

            total_episodes = series.episodes.filter(is_active=True).count()
            if series.total_episodes != total_episodes:
                series.total_episodes = total_episodes
                series.save(update_fields=['total_episodes', 'updated_at'])

        self.stdout.write(self.style.SUCCESS('Demo dramas seeded successfully.'))
