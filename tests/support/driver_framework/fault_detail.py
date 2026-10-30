"""Shared structured-fault input; no collected-test imports."""
def fault(**changes):
    return dict(code='DEVICE_ERROR',source='driver',execution_state='unknown',operation_id='step',
                location=None,native_details={},schema='culsma_device_fault_v2',
                reason='culsma.tip.pickup_failed',basis='device_feedback',
                context={'channel':'1','planned_location':'B / 4'},stop_observation={'state':'unknown'},**changes)
