from django.db import migrations, models
import django.db.models.deletion


DEFAULT_CATEGORIES = [
    ('Technology', 'technology', 10),
    ('Education', 'education', 20),
    ('Gaming', 'gaming', 30),
    ('News', 'news', 40),
    ('Entertainment', 'entertainment', 50),
    ('Other', 'other', 60),
]


def migrate_video_categories(apps, schema_editor):
    Category = apps.get_model('accounts', 'Category')
    Video = apps.get_model('accounts', 'Video')

    slug_map = {
        'tech': 'technology',
        'technology': 'technology',
        'education': 'education',
        'gaming': 'gaming',
        'news': 'news',
        'entertainment': 'entertainment',
        'other': 'other',
    }

    existing = set(Category.objects.values_list('slug', flat=True))
    for name, slug, sort_order in DEFAULT_CATEGORIES:
        if slug not in existing:
            Category.objects.create(
                name=name,
                slug=slug,
                sort_order=sort_order,
                is_active=True,
            )
            existing.add(slug)
        else:
            Category.objects.filter(slug=slug).update(sort_order=sort_order)

    categories_by_slug = {category.slug: category for category in Category.objects.all()}

    for video in Video.objects.all():
        if not video.category:
            continue
        normalized_slug = slug_map.get(video.category, video.category)
        category = categories_by_slug.get(normalized_slug)
        if category is None:
            category = Category.objects.create(
                name=normalized_slug.replace('-', ' ').title(),
                slug=normalized_slug,
                sort_order=999,
                is_active=True,
            )
            categories_by_slug[normalized_slug] = category

        video.category_ref_id = category.id
        video.save(update_fields=['category_ref'])


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0005_category_model_and_video_slug'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='description',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='category',
            name='sort_order',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='video',
            name='category_ref',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='videos',
                to='accounts.category',
            ),
        ),
        migrations.RunPython(migrate_video_categories, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='video',
            name='category',
        ),
        migrations.RenameField(
            model_name='video',
            old_name='category_ref',
            new_name='category',
        ),
    ]
