from django.db import migrations, models
from django.utils.text import slugify


DEFAULT_CATEGORIES = [
    ('Education', 'education'),
    ('Entertainment', 'entertainment'),
    ('Gaming', 'gaming'),
    ('Tech', 'tech'),
    ('Other', 'other'),
]


def seed_categories(apps, schema_editor):
    Category = apps.get_model('accounts', 'Category')
    Video = apps.get_model('accounts', 'Video')

    existing_slugs = set(Category.objects.values_list('slug', flat=True))
    for name, slug in DEFAULT_CATEGORIES:
        if slug not in existing_slugs:
            Category.objects.create(name=name, slug=slug, is_active=True)
            existing_slugs.add(slug)

    for raw_category in Video.objects.exclude(category='').values_list('category', flat=True).distinct():
        slug = slugify(raw_category)
        if not slug:
            continue
        if slug not in existing_slugs:
            Category.objects.create(
                name=raw_category.replace('-', ' ').title(),
                slug=slug,
                is_active=True,
            )
            existing_slugs.add(slug)
        Video.objects.filter(category=raw_category).update(category=slug)


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0004_video_thumbnail'),
    ]

    operations = [
        migrations.CreateModel(
            name='Category',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
                ('slug', models.SlugField(max_length=100, unique=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.AlterField(
            model_name='video',
            name='category',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.RunPython(seed_categories, migrations.RunPython.noop),
    ]
