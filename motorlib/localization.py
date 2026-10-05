"""Translation metadata without Qt dependencies or localized model values."""


class DisplayText(str):
    """An English string with the source template retained for UI translation.

    Equality, logging and string concatenation retain the canonical English
    behavior. This metadata is for labels and diagnostics, never identifiers,
    enum values or serialized property values.
    """

    def __new__(cls, context, source, args=(), kwargs=None):
        kwargs = kwargs or {}
        value = source.format(*args, **kwargs) if args or kwargs else source
        instance = super().__new__(cls, value)
        instance.context = context
        instance.source = source
        instance.args = args
        instance.kwargs = kwargs
        return instance

    def format(self, *args, **kwargs):
        return DisplayText(self.context, self.source, args, kwargs)

    def __reduce__(self):
        return DisplayText, (self.context, self.source, self.args, self.kwargs)


def QT_TRANSLATE_NOOP(context, source):
    """Mark literal templates for pylupdate6 while keeping English model text."""
    return DisplayText(context, source)
