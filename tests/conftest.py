from hypothesis import settings

settings.register_profile("ci", derandomize=True, deadline=None, max_examples=30)
settings.load_profile("ci")
