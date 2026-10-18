import pytest

from culsma_os.program_manager.interactors.verification import CheckpointVerificationInteractor


class TestCheckpointVerification:
    @pytest.mark.parametrize('capacity', [True, 0, -1, '8', 1.5])
    def test_invalid_capacity_rejects(self, capacity):
        with pytest.raises(ValueError, match='CHECKPOINT_CACHE_CAPACITY_INVALID'):
            CheckpointVerificationInteractor(capacity)

    def test_only_identical_checkpoint_bytes_reuse_verification(self):
        cache = CheckpointVerificationInteractor()
        original = '{"revision":1}'
        changed = '{"revision": 1}'
        assert not cache.is_verified(original)
        cache.remember(original)
        assert cache.is_verified(original)
        assert not cache.is_verified(changed)

    def test_recent_verification_is_retained_with_bounded_capacity(self):
        cache = CheckpointVerificationInteractor(capacity=2)
        cache.remember('one')
        cache.remember('two')
        assert cache.is_verified('one')
        cache.remember('three')
        assert cache.is_verified('one') and cache.is_verified('three')
        assert not cache.is_verified('two')
