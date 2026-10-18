"""Adapt the existing language Driver interface to OS-owned execution records."""


class SemanticReplayDriver:
    def __init__(self, effects):
        self.effects = effects

    def check(self, step):
        return self.effects.check(step)

    def execute(self, step):
        return self.effects.execute(step)

    @property
    def supports_group_execution(self):
        return self.effects.supports_group_execution

    def execute_group(self, group):
        return self.effects.execute_group(group)
