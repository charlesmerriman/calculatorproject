from django.apps import AppConfig


class CalculatorapiConfig(AppConfig):
    name = 'calculatorapi'
    # Section heading shown in the Django admin (default would be "Calculatorapi").
    verbose_name = 'Uma Musume Data'

    def ready(self):
        # Connects the content-write signals that drop the cached
        # /calculator-data payload. Imported here rather than at module scope
        # because ready() is the first point at which the model registry is
        # populated. -> calculatorapi/public_payload_cache.py
        from calculatorapi import public_payload_cache  # pylint: disable=import-outside-toplevel
        public_payload_cache.connect_invalidation_signals()
