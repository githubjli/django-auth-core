from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.accounts'

    def ready(self):
        from django.apps import apps
        from django.contrib import admin
        from django.contrib.admin.sites import AlreadyRegistered

        for model in apps.get_models():
            try:
                admin.site.register(model)
            except AlreadyRegistered:
                continue
