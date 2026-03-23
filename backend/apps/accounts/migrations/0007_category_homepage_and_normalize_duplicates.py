from django.db import migrations, models


LEGACY_CATEGORY_SLUG_ALIASES = {
    'tech': 'technology',
}


PRIMARY_HOMEPAGE_SLUGS = {
    'technology',
    'education',
    'gaming',
    'news',
    'entertainment',
}


def normalize_categories(apps, schema_editor):
    Category = apps.get_model('accounts', 'Category')
    Video = apps.get_model('accounts', 'Video')

    categories = {category.slug: category for category in Category.objects.all()}
    for legacy_slug, canonical_slug in LEGACY_CATEGORY_SLUG_ALIASES.items():
        legacy_category = categories.get(legacy_slug)
        canonical_category = categories.get(canonical_slug)
        if legacy_category and canonical_category:
            Video.objects.filter(category=legacy_category).update(category=canonical_category)
            legacy_category.delete()

    for category in Category.objects.all():
        category.show_on_homepage = category.slug in PRIMARY_HOMEPAGE_SLUGS
        category.save(update_fields=['show_on_homepage'])


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0006_category_fields_and_video_fk'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='show_on_homepage',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(normalize_categories, migrations.RunPython.noop),
    ]
