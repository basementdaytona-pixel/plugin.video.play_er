"""Resolve model fields without network access or changing stored preferences."""


def gemini_model_selection(addon):
    custom = addon.getSettingString('gemini_model_id').strip()
    if custom.startswith('models/'):
        custom = custom[len('models/'):].strip()
    preset = addon.getSettingString('gemini_model').strip() or 'gemini-3.5-flash-lite'
    return custom or preset, bool(custom)


def openrouter_model(addon):
    custom = addon.getSettingString('openrouter_model').strip()
    if custom:
        return custom
    preset = addon.getSettingString('openrouter_model_preset').strip()
    return preset if preset and preset != 'custom' else 'google/gemma-4-31b-it:free'
