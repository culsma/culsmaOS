"""Reuse verification of identical immutable checkpoint bytes within one host."""
from collections import OrderedDict
from hashlib import sha256


class CheckpointVerificationInteractor:
    def __init__(self, capacity=8):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("CHECKPOINT_CACHE_CAPACITY_INVALID")
        self.capacity = capacity
        self.verified = OrderedDict()

    def is_verified(self, checkpoint):
        key = sha256(checkpoint.encode()).hexdigest()
        if key not in self.verified:
            return False
        self.verified.move_to_end(key)
        return True

    def remember(self, checkpoint):
        key = sha256(checkpoint.encode()).hexdigest()
        self.verified[key] = None
        self.verified.move_to_end(key)
        while len(self.verified) > self.capacity:
            self.verified.popitem(last=False)
