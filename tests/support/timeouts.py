"""Bounded polling budgets shared by in-process and CLI resident tests."""
import os


class ResidentWaitBudget:
    @staticmethod
    def wait_budget(seconds):
        try:
            multiplier = int(os.environ.get('CULSMA_OS_TEST_TIMEOUT_MULTIPLIER', '1'))
        except ValueError as error:
            raise ValueError('TEST_TIMEOUT_MULTIPLIER_INVALID') from error
        if not 1 <= multiplier <= 10:
            raise ValueError('TEST_TIMEOUT_MULTIPLIER_INVALID')
        return seconds * multiplier
